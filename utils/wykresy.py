"""Wykresy i wskaźniki: sparkline, przebieg, heatmapa, kondycja, budżet."""

import flet as ft
import flet_charts as fc
from date import parsuj_date
from datetime import datetime, timedelta
from state import MIESIACE_NAZWY

from .stale import FS, IKONY_PODZRODEL_ODCZYTU, IKONY_ZRODEL_PRZEBIEGU, KOLORY_ZRODEL_PRZEBIEGU, KOLOR_STATUS, RADIUS, SPACING, formatuj_liczba, ikona_z_mapy
from .format import _odmiana_liczby, symbol_waluty
from .wyglad import _mieszaj_kolory, powierzchnia_karty
from .formularze import karta_formularza


# Punkty kontrolne skali kondycji (odcienie Material 700).
_SKALA_KONDYCJI = [
    (0, (211, 47, 47)),     # RED_700    — wymaga pilnej reakcji
    (50, (245, 124, 0)),    # ORANGE_700 — wymaga uwagi
    (100, (46, 125, 50)),   # GREEN_700  — bardzo dobra
]


def kolor_kondycji_plynny(wynik):
    """Kolor wskaźnika kondycji jako PŁYNNE przejście czerwień → bursztyn →
    zieleń, zamiast trzech skokowych progów. Na kołowym wskaźniku widać dzięki
    temu różnicę między 79 a 81 punktami — przy progach obie wartości wyglądały
    identycznie po jednej i drugiej stronie granicy."""
    if wynik is None:
        return ft.Colors.ON_SURFACE_VARIANT
    try:
        w = max(0.0, min(100.0, float(wynik)))
    except (TypeError, ValueError):
        return ft.Colors.ON_SURFACE_VARIANT

    for (x0, c0), (x1, c1) in zip(_SKALA_KONDYCJI, _SKALA_KONDYCJI[1:]):
        if w <= x1:
            r, g, b = _mieszaj_kolory(c0, c1, (w - x0) / (x1 - x0))
            return f"#{r:02X}{g:02X}{b:02X}"
    r, g, b = _SKALA_KONDYCJI[-1][1]
    return f"#{r:02X}{g:02X}{b:02X}"


def gauge_kondycji(wynik, rozmiar=72, grubosc=7, rozmiar_liczby=None, pokaz_max=True):
    """Kołowy wskaźnik kondycji (0-100) — pierścień wypełniony proporcjonalnie do
    wyniku, w kolorze płynnie przechodzącym od czerwieni do zieleni, z liczbą
    w środku. Zastępuje sam tekst „82/100”: wypełnienie i barwa niosą ocenę,
    więc kafelek da się odczytać jednym spojrzeniem, bez czytania liczby."""
    kolor = kolor_kondycji_plynny(wynik)
    rozmiar_liczby = rozmiar_liczby or max(14, int(rozmiar * 0.30))

    try:
        czysty = max(0, min(100, int(round(float(wynik))))) if wynik is not None else None
    except (TypeError, ValueError):
        czysty = None

    srodek = [
        ft.Text(
            str(czysty) if czysty is not None else "—",
            size=rozmiar_liczby, weight="bold", color=kolor, no_wrap=True,
        )
    ]
    if pokaz_max and czysty is not None:
        srodek.append(ft.Text("/100", size=max(8, int(rozmiar_liczby * 0.42)),
                              color=ft.Colors.ON_SURFACE_VARIANT))

    return ft.Stack([
        ft.ProgressRing(
            value=(czysty / 100) if czysty is not None else 0.0,
            width=rozmiar, height=rozmiar, stroke_width=grubosc,
            color=kolor, stroke_cap=ft.StrokeCap.ROUND,
            bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
        ),
        ft.Container(
            width=rozmiar, height=rozmiar, alignment=ft.Alignment.CENTER,
            content=ft.Column(srodek, spacing=0, tight=True,
                              horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        ),
    ], width=rozmiar, height=rozmiar)


def pasek_budzetu(page: ft.Page, stan, pokaz_szczegoly=True):
    """Wykorzystanie jednego limitu. Poza samym paskiem rysujemy pionowy
    ZNACZNIK UPŁYWU OKRESU — miejsce, w którym wypadałoby być dzisiaj, gdyby
    wydawać równo. Bez niego „62% limitu” nic nie mówi: w połowie miesiąca to
    kłopot, a 28. dnia powód do zadowolenia."""
    kolor = {
        "przekroczony": ft.Colors.RED_700,
        "uwaga": ft.Colors.ORANGE_700,
        "ok": ft.Colors.GREEN_700,
    }.get(stan.get("status"), ft.Colors.PRIMARY)

    udzial = min(1.0, (stan["procent"] or 0) / 100)
    udzial_czasu = min(1.0, stan["dni_minione"] / stan["dni_okresu"]) if stan.get("dni_okresu") else 0

    WYSOKOSC = 10
    pasek = ft.Stack([
        ft.Container(
            height=WYSOKOSC, border_radius=RADIUS["xs"],
            bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
        ),
        ft.Row([
            ft.Container(
                height=WYSOKOSC, border_radius=RADIUS["xs"], bgcolor=kolor,
                expand=max(1, int(udzial * 1000)),
                animate=ft.Animation(400, ft.AnimationCurve.EASE_OUT),
            ),
            ft.Container(expand=max(1, int((1 - udzial) * 1000))),
        ], spacing=0),
        # Znacznik „gdzie powinieneś być dzisiaj” — cienka kreska w poprzek paska.
        ft.Row([
            ft.Container(expand=max(1, int(udzial_czasu * 1000))),
            ft.Container(width=2, height=WYSOKOSC + 6, bgcolor=ft.Colors.ON_SURFACE,
                         border_radius=1, tooltip="Tyle okresu już minęło"),
            ft.Container(expand=max(1, int((1 - udzial_czasu) * 1000))),
        ], spacing=0, alignment=ft.MainAxisAlignment.START),
    ], height=WYSOKOSC + 6)

    naglowek = ft.Row([
        ft.Text(stan["etykieta_kategorii"], size=FS["body_strong"], weight="bold", expand=True,
                no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
        ft.Text(f"{formatuj_liczba(stan['wydano'])} / {formatuj_liczba(stan['limit'])} {symbol_waluty()}",
                size=FS["body"], weight="bold", color=kolor),
    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

    elementy = [naglowek, pasek]

    if pokaz_szczegoly:
        if stan["status"] == "przekroczony":
            podpis = (f"Przekroczony o {formatuj_liczba(abs(stan['pozostalo']))} {symbol_waluty()}"
                      f" • {formatuj_liczba(stan['procent'], 0)}% limitu")
        elif stan.get("dzien_przekroczenia"):
            podpis = (f"Zostało {formatuj_liczba(stan['pozostalo'])} {symbol_waluty()}"
                      f" • w tym tempie limit padnie {stan['dzien_przekroczenia']}")
        else:
            podpis = (f"Zostało {formatuj_liczba(stan['pozostalo'])} {symbol_waluty()}"
                      f" na {stan['dni_pozostalo']} dni ({stan['etykieta_okresu'].lower()})")
        elementy.append(ft.Text(podpis, size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT))

    return ft.Column(elementy, spacing=SPACING["xs"])


def wskaznik_baku(page: ft.Page, dane, kompaktowy=False):
    """Poziomy wskaźnik pozostałego paliwa z zasięgiem w kilometrach.
    Zawsze z notą o szacunku — to wyliczenie z licznika i średniego zużycia,
    a nie odczyt z pływaka, i użytkownik musi to wiedzieć, zanim zaufa liczbie
    na trasie."""
    if not dane:
        return ft.Container(width=0, height=0)

    procent = dane.get("procent_baku")
    zasieg = dane.get("zasieg_pozostaly")
    if procent is None:
        kolor = ft.Colors.BLUE_GREY_700
    elif procent < 15:
        kolor = ft.Colors.RED_700
    elif procent < 30:
        kolor = ft.Colors.ORANGE_700
    else:
        kolor = ft.Colors.GREEN_700

    gorny = ft.Row([
        ft.Row([
            ft.Icon(ft.Icons.LOCAL_GAS_STATION, size=16, color=kolor),
            ft.Text("Szacowany zasięg", size=FS["label"], color=ft.Colors.ON_SURFACE_VARIANT),
        ], spacing=6),
        ft.Text(f"{formatuj_liczba(zasieg, 0)} km" if zasieg is not None else "—",
                size=FS["title"], weight="bold", color=kolor),
    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

    elementy = [gorny]
    if procent is not None:
        elementy.append(ft.ProgressBar(
            value=max(0.0, min(1.0, procent / 100)), color=kolor,
            bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
            height=8, border_radius=4,
        ))

    if not kompaktowy:
        czesci = []
        if dane.get("pojemnosc"):
            czesci.append(f"bak {formatuj_liczba(dane['pojemnosc'], 0)} l")
        if dane.get("pozostalo_jednostek") is not None:
            czesci.append(f"~{formatuj_liczba(dane['pozostalo_jednostek'], 1)} l w baku")
        if dane.get("zasieg_pelny"):
            czesci.append(f"pełny bak ≈ {formatuj_liczba(dane['zasieg_pelny'], 0)} km")
        elementy.append(ft.Text(" • ".join(czesci), size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT))

        nota = {
            "wysoka": "Szacunek z licznika i Twojego zużycia — nie z czujnika w aucie.",
            "srednia": "Szacunek z licznika; od ostatniego tankowania minęło już trochę czasu.",
            "niska": "Szacunek mocno przybliżony — ostatnie tankowanie do pełna jest stare.",
            "brak": "Brak tankowania do pełna, więc liczy się tylko zasięg na pełnym baku.",
        }.get(dane.get("pewnosc"), "")
        if nota:
            elementy.append(ft.Row([
                ft.Icon(ft.Icons.INFO_OUTLINE, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(nota, size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
            ], spacing=5))

    return ft.Column(elementy, spacing=SPACING["xs"])


def karta_analizy(page: ft.Page, tytul, ikona, zawartosc, kolor=None):
    """Sekcja zakładki Analiza: nagłówek z ikoną i treść na jednej powierzchni."""
    kolor = kolor or ft.Colors.PRIMARY
    return ft.Container(
        padding=SPACING["lg"], border_radius=RADIUS["lg"],
        **powierzchnia_karty(page, "md"),
        content=ft.Column([
            ft.Row([
                ft.Icon(ikona, size=18, color=kolor),
                ft.Text(tytul, size=FS["title"], weight="bold"),
            ], spacing=SPACING["sm"]),
            ft.Column(zawartosc if isinstance(zawartosc, list) else [zawartosc], spacing=SPACING["sm"]),
        ], spacing=SPACING["sm"]),
    )


def sparkline(wartosci, kolor=None, wysokosc=30, szerokosc=None, wypelnienie=True,
              grubosc=2, punkty_koncowe=True):
    """Mini-wykres liniowy bez osi, siatki i etykiet — „iskra” pokazująca sam
    kształt trendu obok liczby (patrz kafelek „Śr. spalanie” w kokpicie).

    `wartosci`: lista liczb w kolejności chronologicznej. Przy mniej niż 2
    sensownych punktach zwraca None — wywołujący sam decyduje, co pokazać
    zamiast wykresu. Skala Y jest dociskana do zakresu danych (z niewielkim
    zapasem), bo w sparkline liczy się różnica między punktami, a nie odległość
    od zera."""
    liczby = []
    for w in (wartosci or []):
        try:
            liczby.append(float(w))
        except (TypeError, ValueError):
            continue
    if len(liczby) < 2:
        return None

    kolor = kolor or ft.Colors.PRIMARY
    minimum, maksimum = min(liczby), max(liczby)
    # Płaska seria (same identyczne wartości) dałaby zerową wysokość wykresu —
    # wymuszamy wtedy minimalny zapas, żeby linia wylądowała pośrodku.
    zapas = max((maksimum - minimum) * 0.20, abs(maksimum) * 0.02, 0.1)

    def pusta_os():
        # Każde gniazdo osi musi dostać WŁASNĄ instancję — jednej kontrolki Flet
        # nie da się wpiąć w kilka miejsc drzewa naraz.
        return fc.ChartAxis(show_labels=False, label_size=0, title_size=0)

    return ft.Container(
        height=wysokosc, width=szerokosc,
        content=fc.LineChart(
            data_series=[
                fc.LineChartData(
                    points=[fc.LineChartDataPoint(i, w) for i, w in enumerate(liczby)],
                    stroke_width=grubosc,
                    color=kolor,
                    curved=True,
                    rounded_stroke_cap=True,
                    point=False,
                    below_line_bgcolor=ft.Colors.with_opacity(0.15, kolor) if wypelnienie else None,
                )
            ],
            left_axis=pusta_os(), right_axis=pusta_os(),
            top_axis=pusta_os(), bottom_axis=pusta_os(),
            min_x=0, max_x=len(liczby) - 1,
            min_y=minimum - zapas, max_y=maksimum + zapas,
            interactive=False,
            expand=True,
        ),
    )


def odznaka_zrodla_przebiegu(zrodlo, etykieta, podzrodlo=None, rozmiar=11):
    """Mały chip „skąd ten przebieg”. Przy własnym odczycie dokłada drugą ikonę
    z podźródłem (ręcznie / kokpit / dane pojazdu / import) — bez tego wszystkie
    własne wpisy wyglądałyby identycznie, a to właśnie między nimi najłatwiej
    się pogubić po imporcie kilkuset wierszy."""
    kolor = KOLORY_ZRODEL_PRZEBIEGU.get(zrodlo, ft.Colors.ON_SURFACE_VARIANT)
    tresc = [
        ft.Icon(ikona_z_mapy(IKONY_ZRODEL_PRZEBIEGU, zrodlo, ft.Icons.CIRCLE_OUTLINED),
                size=rozmiar + 2, color=kolor),
        ft.Text(etykieta, size=rozmiar, weight="bold", color=kolor),
    ]
    if podzrodlo:
        tresc.append(ft.Icon(ikona_z_mapy(IKONY_PODZRODEL_ODCZYTU, podzrodlo, ft.Icons.EDIT),
                             size=rozmiar, color=ft.Colors.with_opacity(0.7, kolor)))
    return ft.Container(
        padding=ft.Padding(8, 2, 8, 2), border_radius=RADIUS["pill"],
        bgcolor=ft.Colors.with_opacity(0.13, kolor),
        content=ft.Row(tresc, spacing=4, tight=True),
    )


def wykres_przebiegu(page: ft.Page, wpisy, wysokosc=190):
    """Krzywa stanu licznika w czasie, z punktami pokolorowanymi wg źródła.

    Oś X to DNI od pierwszego wpisu, a nie kolejny numer pozycji — inaczej
    trzymiesięczna przerwa i dwa tankowania w jednym tygodniu wyglądałyby na
    wykresie tak samo, a to właśnie przestoje są tu najciekawsze."""
    punkty = [w for w in (wpisy or []) if w.get("data_obj") and w.get("przebieg")]
    if len(punkty) < 2:
        return None

    start = punkty[0]["data_obj"]
    xy = [((w["data_obj"] - start).days, w["przebieg"], w["zrodlo"]) for w in punkty]
    maks_x = max(x for x, _, _ in xy) or 1
    wart_y = [y for _, y, _ in xy]
    min_y, maks_y = min(wart_y), max(wart_y)
    zapas = max((maks_y - min_y) * 0.08, 50)

    dane_punkty = [
        fc.LineChartDataPoint(
            x, y,
            point=fc.ChartCirclePoint(
                color=KOLORY_ZRODEL_PRZEBIEGU.get(zrodlo, ft.Colors.PRIMARY),
                radius=3.5, stroke_width=0,
            ),
            tooltip=f"{punkty[i]['data']}\n{formatuj_liczba(y, 0)} km\n{punkty[i]['etykieta_zrodla']}",
        )
        for i, (x, y, zrodlo) in enumerate(xy)
    ]

    def etykieta_daty(indeks):
        return fc.ChartAxisLabel(
            value=xy[indeks][0],
            label=ft.Text(punkty[indeks]["data"][3:], size=9, color=ft.Colors.ON_SURFACE_VARIANT),
        )

    # Trzy podpisy na osi czasu (początek, środek, koniec) — więcej nachodziłoby
    # na siebie na szerokości telefonu.
    indeksy_dat = sorted({0, len(punkty) // 2, len(punkty) - 1})

    return ft.Container(
        height=wysokosc,
        padding=ft.Padding(0, SPACING["sm"], SPACING["sm"], 0),
        content=fc.LineChart(
            data_series=[fc.LineChartData(
                points=dane_punkty, stroke_width=2, color=ft.Colors.PRIMARY,
                curved=False, rounded_stroke_cap=True,
                below_line_bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.PRIMARY),
            )],
            horizontal_grid_lines=fc.ChartGridLines(
                interval=max(1, int((maks_y - min_y) / 3) or 1),
                color=ft.Colors.with_opacity(0.10, ft.Colors.ON_SURFACE), width=1,
            ),
            left_axis=fc.ChartAxis(
                labels=[
                    fc.ChartAxisLabel(
                        value=wartosc,
                        label=ft.Text(f"{formatuj_liczba(wartosc / 1000, 0)} tys.", size=9,
                                      color=ft.Colors.ON_SURFACE_VARIANT),
                    )
                    for wartosc in (min_y, (min_y + maks_y) / 2, maks_y)
                ],
                label_size=44, title_size=0,
            ),
            bottom_axis=fc.ChartAxis(
                labels=[etykieta_daty(i) for i in indeksy_dat],
                label_size=22, title_size=0,
            ),
            right_axis=fc.ChartAxis(show_labels=False, label_size=0, title_size=0),
            top_axis=fc.ChartAxis(show_labels=False, label_size=0, title_size=0),
            min_x=0, max_x=maks_x,
            min_y=min_y - zapas, max_y=maks_y + zapas,
            interactive=True,
            expand=True,
        ),
    )


def znacznik_trendu(zmiana_proc, prog=5, wzrost_zly=True, rozmiar=11):
    """Mały „chip” trendu: strzałka + procent zmiany. `wzrost_zly=True` znaczy,
    że rosnąca wartość jest zła (koszty, spalanie) i dostaje kolor czerwony.
    Zwraca ft.Row gotowy do wstawienia pod wartością na kafelku."""
    try:
        zmiana = float(zmiana_proc)
    except (TypeError, ValueError):
        return ft.Row([
            ft.Icon(ft.Icons.TRENDING_FLAT, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Text("Brak trendu", size=rozmiar, color=ft.Colors.ON_SURFACE_VARIANT, no_wrap=True),
        ], spacing=4)

    if zmiana > prog:
        ikona = ft.Icons.TRENDING_UP
        kolor = KOLOR_STATUS["critical"] if wzrost_zly else KOLOR_STATUS["ok"]
        tekst = f"+{formatuj_liczba(zmiana, 0)}%"
    elif zmiana < -prog:
        ikona = ft.Icons.TRENDING_DOWN
        kolor = KOLOR_STATUS["ok"] if wzrost_zly else KOLOR_STATUS["critical"]
        tekst = f"{formatuj_liczba(zmiana, 0)}%"
    else:
        ikona, kolor, tekst = ft.Icons.TRENDING_FLAT, KOLOR_STATUS["neutral"], "Stabilnie"

    return ft.Row([
        ft.Icon(ikona, size=13, color=kolor),
        ft.Text(tekst, size=rozmiar, color=kolor, no_wrap=True),
    ], spacing=4)


def pasek_postepu(etykieta_lewa, etykieta_prawa, procent, kolor, wysokosc=8):
    """Wspólny 'wiersz postępu': etykieta + wartość nad kolorowym ProgressBar.
    procent: 0.0-1.0 (spoza zakresu jest przycinane). Wydzielone z _pasek_porownania
    (porownanie_view.py) — używane tam i na kartach zadań serwisowych (buduj_serwis)."""
    return ft.Column([
        ft.Row([
            ft.Text(etykieta_lewa, size=12, weight="bold", expand=True, no_wrap=True),
            ft.Text(etykieta_prawa, size=12, weight="bold", color=kolor)
        ]),
        ft.ProgressBar(value=max(0.03, min(1.0, procent)), color=kolor,
                       bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE), height=wysokosc, border_radius=4)
    ], spacing=4)


def heatmapa_aktywnosci(page: ft.Page, daty_zdarzen, tygodnie=53):
    """Heatmapa aktywności w stylu GitHub 'contributions': siatka kwadracików
    (kolumna = tydzień, wiersz = dzień tygodnia) pokazująca, w które dni z
    ostatniego roku pojawiło się jakiekolwiek zdarzenie w dzienniku auta.
    `daty_zdarzen`: dowolna iterowalna surowych dat tekstowych (DD.MM.YYYY);
    kilka zdarzeń tego samego dnia jest sumowanych. Używane przez /timeline."""
    liczba_wg_dnia = {}
    for data_str in daty_zdarzen:
        d = parsuj_date(data_str)
        if d == datetime.min.date():
            continue
        liczba_wg_dnia[d] = liczba_wg_dnia.get(d, 0) + 1

    dzis = datetime.now().date()
    koniec = dzis + timedelta(days=(6 - dzis.weekday()))  # zaokrąglenie w górę do niedzieli
    poczatek = koniec - timedelta(days=tygodnie * 7 - 1)
    maks = max(liczba_wg_dnia.values(), default=0)

    def kolor_dnia(n):
        if n <= 0:
            return ft.Colors.with_opacity(0.06, ft.Colors.ON_SURFACE)
        if maks <= 1:
            return ft.Colors.with_opacity(0.85, ft.Colors.PRIMARY)
        udzial = n / maks
        poziom = 0.30 if udzial <= 0.25 else 0.55 if udzial <= 0.5 else 0.75 if udzial <= 0.75 else 0.95
        return ft.Colors.with_opacity(poziom, ft.Colors.PRIMARY)

    WYM = 11
    kursor = poczatek
    poprzedni_miesiac = None
    kolumny_tygodni = []
    aktywne_dni = 0

    for _ in range(tygodnie):
        if kursor.month != poprzedni_miesiac:
            naglowek = ft.Container(height=14, content=ft.Text(MIESIACE_NAZWY[kursor.month - 1][:3], size=10, color=ft.Colors.ON_SURFACE_VARIANT))
            poprzedni_miesiac = kursor.month
        else:
            naglowek = ft.Container(height=14)

        komorki = [naglowek]
        for _ in range(7):
            if kursor > dzis:
                komorki.append(ft.Container(width=WYM, height=WYM))
            else:
                n = liczba_wg_dnia.get(kursor, 0)
                if n:
                    aktywne_dni += 1
                komorki.append(ft.Container(
                    width=WYM, height=WYM, border_radius=3, bgcolor=kolor_dnia(n),
                    tooltip=f"{kursor.strftime('%d.%m.%Y')}: {n} {_odmiana_liczby(n, 'wpis', 'wpisy', 'wpisów')}" if n else kursor.strftime("%d.%m.%Y"),
                ))
            kursor += timedelta(days=1)

        kolumny_tygodni.append(ft.Column(komorki, spacing=3))

    # Odwracamy kolejność kolumn — najnowszy tydzień ma być widoczny od razu
    # (po lewej), bez przewijania w prawo, żeby go zobaczyć.
    siatka = ft.Row(list(reversed(kolumny_tygodni)), spacing=3, scroll=ft.ScrollMode.AUTO)

    def kw_legendy(poziom, kolor_bazowy=None):
        return ft.Container(width=WYM, height=WYM, border_radius=3, bgcolor=ft.Colors.with_opacity(poziom, kolor_bazowy or ft.Colors.PRIMARY))

    legenda = ft.Row([
        ft.Text("Mniej", size=10, color=ft.Colors.ON_SURFACE_VARIANT),
        kw_legendy(0.06, ft.Colors.ON_SURFACE), kw_legendy(0.30), kw_legendy(0.55), kw_legendy(0.75), kw_legendy(0.95),
        ft.Text("Więcej", size=10, color=ft.Colors.ON_SURFACE_VARIANT),
    ], spacing=4)

    opis = f"Najnowszy tydzień po lewej • {aktywne_dni} {_odmiana_liczby(aktywne_dni, 'aktywny dzień', 'aktywne dni', 'aktywnych dni')} w ciągu ostatniego roku."

    return karta_formularza(
        [siatka, legenda, ft.Text(opis, size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT)],
        "Aktywność w ciągu roku", ft.Icons.CALENDAR_MONTH, domyslnie_otwarte=True, page=page
    )


__all__ = [
    "_SKALA_KONDYCJI",
    "gauge_kondycji",
    "heatmapa_aktywnosci",
    "karta_analizy",
    "kolor_kondycji_plynny",
    "odznaka_zrodla_przebiegu",
    "pasek_budzetu",
    "pasek_postepu",
    "sparkline",
    "wskaznik_baku",
    "wykres_przebiegu",
    "znacznik_trendu",
]
