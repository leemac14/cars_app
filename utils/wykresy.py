"""Wykresy i wskaźniki: sparkline, przebieg, heatmapa, kondycja, budżet."""

import db
import flet as ft
import flet_charts as fc
from date import parsuj_date
from datetime import date, datetime, timedelta
from state import MIESIACE_NAZWY

from .animacje import ScenaWejscia
from .stale import FS, IKONY_PODZRODEL_ODCZYTU, IKONY_ZRODEL_PRZEBIEGU, KOLORY_ZRODEL_PRZEBIEGU, KOLOR_STATUS, RADIUS, SPACING, formatuj_liczba, ikona_z_mapy
from .format import MIESIACE_MIEJSCOWNIK, _odmiana_liczby, formatuj_dni, formatuj_dystans, jednostka_dystansu, opis_licznika_na_karte, symbol_waluty
from .typografia import etykieta, podpis, wartosc
from .wyglad import _mieszaj_kolory, pasek_przewijany, powierzchnia, tlo_karty, tlo_odznaki, tlo_toru
from .dialogi import odswiez_ekran
from .formularze import karta_formularza


# Punkty kontrolne skali kondycji (odcienie Material 700).
_SKALA_KONDYCJI = [
    (0, (211, 47, 47)),     # RED_700    — wymaga pilnej reakcji
    (50, (245, 124, 0)),    # ORANGE_700 — wymaga uwagi
    (100, (46, 125, 50)),   # GREEN_700  — bardzo dobra
]


# ---------------------- ZAKRES CZASU NAD WYKRESEM ----------------------
# Jeden komponent dla wszystkich wykresów w aplikacji. Wcześniej każdy wykres
# miał zakres zaszyty w kodzie — wydatki sześć miesięcy, reszta całą historię —
# i przy kilkuletnim dzienniku obie wartości były złe, tylko w przeciwnych
# kierunkach: jedna gubiła poprzedni sezon, druga zgniatała ostatnie miesiące
# w kreskę przy krawędzi.
ZAKRESY_CZASU = [("3 mies.", 3), ("6 mies.", 6), ("Rok", 12), ("Wszystko", 0)]

_OPISY_ZAKRESU = {
    3: "ostatnie 3 miesiące",
    6: "ostatnie 6 miesięcy",
    12: "ostatni rok",
    0: "całą historię",
}


def opis_zakresu(miesiace):
    """Zakres słowami — do podpisów i podpowiedzi nad wykresem."""
    return _OPISY_ZAKRESU.get(miesiace, _OPISY_ZAKRESU[12])


def _przesun_miesiac(rok, miesiac, wstecz):
    miesiac -= wstecz
    while miesiac <= 0:
        miesiac += 12
        rok -= 1
    return rok, miesiac


def zakres_wykresu(state, klucz):
    """Ile miesięcy wstecz pokazuje wykres `klucz` dla bieżącego pojazdu;
    0 = cała historia. Wybór siedzi w ustawieniach, więc przeżywa restart."""
    return db.pobierz_zakres_wykresu(getattr(state, "auto_id", None), klucz)


def granica_zakresu(miesiace, dzisiaj=None):
    """Pierwszy dzień najstarszego miesiąca mieszczącego się w zakresie;
    None dla „Wszystko”.

    Granica jest MIESIĘCZNA, a nie „dzisiaj minus 90 dni”: wykresy grupują dane
    po miesiącach, więc cięcie w połowie miesiąca zrobiłoby z najstarszego
    słupka ogryzek i pokazało spadek, którego nie było."""
    if not miesiace:
        return None
    dzis = dzisiaj or datetime.now().date()
    rok, mies = _przesun_miesiac(dzis.year, dzis.month, miesiace - 1)
    return date(rok, mies, 1)


def klucze_miesiecy_zakresu(miesiace, najstarszy_mc=None, dzisiaj=None):
    """Kolejne miesiące zakresu jako "RRRR-MM", od najstarszego do bieżącego.
    Dla „Wszystko” zaczyna od `najstarszy_mc` (najstarszy miesiąc z danymi)."""
    dzis = dzisiaj or datetime.now().date()
    if miesiace:
        rok, mies = _przesun_miesiac(dzis.year, dzis.month, miesiace - 1)
    elif najstarszy_mc and len(najstarszy_mc) >= 7 and najstarszy_mc[:4].isdigit():
        rok, mies = int(najstarszy_mc[:4]), int(najstarszy_mc[5:7])
    else:
        rok, mies = dzis.year, dzis.month

    klucze = []
    # Zapis w bazie bywa ręczny, a data z 1900 roku zrobiłaby z tej pętli
    # tysiąc słupków — stąd twardy sufit na długość osi.
    while (rok, mies) <= (dzis.year, dzis.month) and len(klucze) < 600:
        klucze.append(f"{rok}-{mies:02d}")
        mies += 1
        if mies > 12:
            mies, rok = 1, rok + 1
    return klucze or [f"{dzis.year}-{dzis.month:02d}"]


def okresy_slupkow(miesiace, najstarszy_mc=None, dzisiaj=None):
    """Siatka słupków wykresu słupkowego: [(etykieta, [klucze miesięcy]), ...]
    od najstarszego do najnowszego.

    Do roku włącznie słupek = miesiąc. „Wszystko” przy dłuższej historii zbija
    miesiące w kwartały, a powyżej trzech lat w lata — trzydzieści sześć
    słupków zmieściłoby się na telefonie tylko jako kreski bez podpisów."""
    klucze = klucze_miesiecy_zakresu(miesiace, najstarszy_mc, dzisiaj)

    if len(klucze) <= 12:
        return [(f"{k[5:7]}/{k[2:4]}", [k]) for k in klucze]

    grupy = {}
    if len(klucze) <= 36:
        for k in klucze:
            grupy.setdefault((k[:4], (int(k[5:7]) - 1) // 3 + 1), []).append(k)
        return [(f"{kw}kw/{rok[2:]}", lista) for (rok, kw), lista in grupy.items()]

    for k in klucze:
        grupy.setdefault(k[:4], []).append(k)
    return [(rok, lista) for rok, lista in grupy.items()]


def tygodnie_zakresu(miesiace, daty_zdarzen=(), dzisiaj=None):
    """Ile kolumn ma mieć heatmapa aktywności dla wybranego zakresu.
    Przy „Wszystko” liczy od najstarszego zdarzenia, ale z sufitem — mapa
    dziesięciu lat to już tylko pasek do przewijania bez końca."""
    dzis = dzisiaj or datetime.now().date()
    granica = granica_zakresu(miesiace, dzis)
    if granica is None:
        daty = [d for d in (parsuj_date(x) for x in daty_zdarzen) if d != datetime.min.date()]
        granica = min(daty) if daty else dzis
    dni = max(0, (dzis - granica).days)
    return max(5, min(261, -(-dni // 7) + 2))


def krok_etykiet_osi(liczba_punktow, ile_podpisow=6):
    """Co który punkt serii dostaje podpis na osi X, żeby przy długim zakresie
    podpisy nie nachodziły na siebie."""
    return max(1, -(-liczba_punktow // max(1, ile_podpisow)))


def pasek_zakresu_czasu(page: ft.Page, state, klucz):
    """Zakres czasu nad wykresem: „3 mies. / 6 mies. / Rok / Wszystko”
    w jednej pigułce dosuniętej do prawej krawędzi.

    `klucz` nazywa WYKRES (np. "wydatki"), bo każdy pamięta swój zakres
    osobno — spalanie z roku obok wydatków z kwartału to normalne pytanie,
    a jeden wspólny przełącznik kazałby zadawać je na raty."""
    auto_id = getattr(state, "auto_id", None)
    aktualny = db.pobierz_zakres_wykresu(auto_id, klucz)

    def wybierz(miesiace):
        db.zapisz_zakres_wykresu(auto_id, klucz, miesiace)
        # Odświeżenie, a nie przebudowa stosu — zakres zmienia ZAWARTOŚĆ
        # wykresu, a nie ekran, na którym stoimy (patrz utils.odswiez_ekran).
        odswiez_ekran(page)

    return _pigulka_chipow(page, ZAKRESY_CZASU, aktualny, wybierz,
                           lambda m: f"Pokaż {opis_zakresu(m)}")


def _pigulka_chipow(page: ft.Page, opcje, aktualny, wybierz, podpowiedz=None):
    """Grupa chipów w jednej pigułce dosuniętej do prawej krawędzi, tuż nad
    wykresem, którego dotyczy — jedna niska linijka zamiast czterech.

    Wspólna dla paska zakresu i paska okna kroczącego: to ten sam gest w tym
    samym miejscu, więc ma wyglądać identycznie."""
    segmenty = []
    for etykieta_chipa, wartosc_chipa in opcje:
        aktywny = (wartosc_chipa == aktualny)
        segmenty.append(ft.Container(
            height=26,
            padding=ft.Padding(10, 0, 10, 0),
            border_radius=RADIUS["pill"],
            ink=True,
            bgcolor=ft.Colors.PRIMARY if aktywny else ft.Colors.TRANSPARENT,
            animate=ft.Animation(180, ft.AnimationCurve.EASE_OUT),
            tooltip=podpowiedz(wartosc_chipa) if podpowiedz else None,
            on_click=lambda e, w=wartosc_chipa: wybierz(w),
            # ANI `alignment`, ANI `expand` — kontener z wyrównaniem rozciąga
            # się do całej szerokości, jaką dostanie, więc cztery takie chipy
            # w pasku zawijanym lądowały jeden pod drugim i zjadały ekran.
            # Bez wyrównania kontener ma rozmiar swojej treści, a `tight=True`
            # pilnuje tego samego po stronie wiersza.
            content=ft.Row(
                [ft.Text(
                    etykieta_chipa, size=FS["caption"],
                    weight="bold" if aktywny else "normal",
                    color=ft.Colors.ON_PRIMARY if aktywny else ft.Colors.ON_SURFACE_VARIANT,
                    no_wrap=True,
                )],
                tight=True,
            ),
        ))

    grupa = ft.Container(
        padding=3, border_radius=RADIUS["pill"], bgcolor=tlo_karty(page, poziom=2),
        content=ft.Row(segmenty, spacing=2, tight=True),
    )
    return ft.Row([grupa], alignment=ft.MainAxisAlignment.END,
                  vertical_alignment=ft.CrossAxisAlignment.CENTER)


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


def gauge_kondycji(wynik, rozmiar=72, grubosc=7, rozmiar_liczby=None, pokaz_max=True, scena=None):
    """Kołowy wskaźnik kondycji (0-100) — pierścień wypełniony proporcjonalnie do
    wyniku, w kolorze płynnie przechodzącym od czerwieni do zieleni, z liczbą
    w środku. Zastępuje sam tekst „82/100”: wypełnienie i barwa niosą ocenę,
    więc kafelek da się odczytać jednym spojrzeniem, bez czytania liczby.

    `scena` (utils.ScenaWejscia) sprawia, że przy wejściu na kokpit pierścień
    napełnia się od zera — razem z liczbą i barwą, więc wskaźnik przejeżdża
    wtedy przez całą skalę od czerwieni do swojego koloru."""
    scena = scena or ScenaWejscia(wlaczona=False)
    kolor = kolor_kondycji_plynny(wynik)
    rozmiar_liczby = rozmiar_liczby or max(14, int(rozmiar * 0.30))

    try:
        czysty = max(0, min(100, int(round(float(wynik))))) if wynik is not None else None
    except (TypeError, ValueError):
        czysty = None

    liczba = ft.Text(
        str(czysty) if czysty is not None else "—",
        size=rozmiar_liczby, weight="bold", color=kolor, no_wrap=True,
    )
    srodek = [liczba]
    if pokaz_max and czysty is not None:
        srodek.append(ft.Text("/100", size=max(8, int(rozmiar_liczby * 0.42)),
                              color=ft.Colors.ON_SURFACE_VARIANT))

    pierscien = ft.ProgressRing(
        value=(czysty / 100) if czysty is not None else 0.0,
        width=rozmiar, height=rozmiar, stroke_width=grubosc,
        color=kolor, stroke_cap=ft.StrokeCap.ROUND,
        bgcolor=tlo_toru(),
    )

    if czysty is not None:
        def _prowadz_gauge(postep, _p=pierscien, _l=liczba, _cel=czysty):
            biezacy = _cel * postep
            barwa = kolor_kondycji_plynny(biezacy)
            _p.value = biezacy / 100
            _p.color = barwa
            _l.value = str(int(round(biezacy)))
            _l.color = barwa

        scena.tor(_prowadz_gauge, pierscien, liczba)

    return ft.Stack([
        pierscien,
        ft.Container(
            width=rozmiar, height=rozmiar, alignment=ft.Alignment.CENTER,
            content=ft.Column(srodek, spacing=0, tight=True,
                              horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        ),
    ], width=rozmiar, height=rozmiar)


def pasek_budzetu(page: ft.Page, stan, pokaz_szczegoly=True, scena=None):
    """Wykorzystanie jednego limitu. Poza samym paskiem rysujemy pionowy
    ZNACZNIK UPŁYWU OKRESU — miejsce, w którym wypadałoby być dzisiaj, gdyby
    wydawać równo. Bez niego „62% limitu” nic nie mówi: w połowie miesiąca to
    kłopot, a 28. dnia powód do zadowolenia. Okno ruchome („ostatnie 30 dni”)
    znacznika nie dostaje — całe leży w przeszłości, więc kreska stałaby zawsze
    na końcu paska i nie mówiłaby nic."""
    scena = scena or ScenaWejscia(wlaczona=False)
    scena.nastepny_wiersz()
    kolor = {
        "przekroczony": KOLOR_STATUS["critical"],
        "uwaga": KOLOR_STATUS["warning"],
        "ok": KOLOR_STATUS["ok"],
    }.get(stan.get("status"), ft.Colors.PRIMARY)

    udzial = min(1.0, (stan["procent"] or 0) / 100)
    ruchomy = bool(stan.get("ruchomy"))
    udzial_czasu = min(1.0, stan["dni_minione"] / stan["dni_okresu"]) if stan.get("dni_okresu") else 0

    WYSOKOSC = 10
    # Wypełnienie i „reszta” trzymane osobno, bo przy wejściu na kokpit pasek
    # najeżdża od zera (patrz scena.udzial) — a `expand` jest polem układu,
    # którego fletowe `animate` nie obejmuje.
    wypelnienie = ft.Container(
        height=WYSOKOSC, border_radius=RADIUS["xs"], bgcolor=kolor,
        expand=max(1, int(udzial * 1000)),
        animate=ft.Animation(400, ft.AnimationCurve.EASE_OUT),
    )
    reszta_paska = ft.Container(expand=max(1, int((1 - udzial) * 1000)))
    scena.udzial(wypelnienie, reszta_paska, udzial)

    warstwy = [
        ft.Container(
            height=WYSOKOSC, border_radius=RADIUS["xs"],
            bgcolor=tlo_toru(page),
        ),
        ft.Row([wypelnienie, reszta_paska], spacing=0),
    ]
    if not ruchomy:
        # Znacznik „gdzie powinieneś być dzisiaj” — cienka kreska w poprzek paska.
        warstwy.append(ft.Row([
            ft.Container(expand=max(1, int(udzial_czasu * 1000))),
            ft.Container(width=2, height=WYSOKOSC + 6, bgcolor=ft.Colors.ON_SURFACE,
                         border_radius=1, tooltip="Tyle okresu już minęło"),
            ft.Container(expand=max(1, int((1 - udzial_czasu) * 1000))),
        ], spacing=0, alignment=ft.MainAxisAlignment.START))
    pasek = ft.Stack(warstwy, height=WYSOKOSC + 6)

    naglowek = ft.Row([
        ft.Text(stan["etykieta_kategorii"], size=FS["body_strong"], weight="bold", expand=True,
                no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
        scena.liczba(
            stan["wydano"],
            lambda v: f"{formatuj_liczba(v)} / {formatuj_liczba(stan['limit'])} {symbol_waluty()}",
            size=FS["body"], weight="bold", color=kolor,
        ),
    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

    elementy = [naglowek, pasek]

    if pokaz_szczegoly:
        if stan["status"] == "przekroczony":
            podpis = (f"Przekroczony o {formatuj_liczba(abs(stan['pozostalo']))} {symbol_waluty()}"
                      f" • {formatuj_liczba(stan['procent'], 0)}% limitu")
        elif stan.get("dzien_przekroczenia"):
            podpis = (f"Zostało {formatuj_liczba(stan['pozostalo'])} {symbol_waluty()}"
                      f" • w tym tempie limit padnie {stan['dzien_przekroczenia']}")
        elif ruchomy:
            # Okno kończy się dzisiaj, więc nie ma „ile dni jeszcze zostało” —
            # jest tylko tyle, ile do limitu brakuje w ostatnich 30 dniach.
            podpis = (f"Zostało {formatuj_liczba(stan['pozostalo'])} {symbol_waluty()}"
                      f" do limitu na {stan['etykieta_okresu'].lower()}")
        else:
            podpis = (f"Zostało {formatuj_liczba(stan['pozostalo'])} {symbol_waluty()}"
                      f" na {formatuj_dni(stan['dni_pozostalo'])} ({stan['etykieta_okresu'].lower()})")
        elementy.append(ft.Text(podpis, size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT))

    return ft.Column(elementy, spacing=SPACING["xs"])


def wskaznik_baku(page: ft.Page, dane, kompaktowy=False, scena=None):
    """Poziomy wskaźnik pozostałego paliwa z zasięgiem w kilometrach.
    Zawsze z notą o szacunku — to wyliczenie z licznika i średniego zużycia,
    a nie odczyt z pływaka, i użytkownik musi to wiedzieć, zanim zaufa liczbie
    na trasie."""
    if not dane:
        return ft.Container(width=0, height=0)

    scena = scena or ScenaWejscia(wlaczona=False)
    scena.nastepny_wiersz()
    procent = dane.get("procent_baku")
    zasieg = dane.get("zasieg_pozostaly")
    if procent is None:
        kolor = ft.Colors.BLUE_GREY_700
    elif procent < 15:
        kolor = KOLOR_STATUS["critical"]
    elif procent < 30:
        kolor = KOLOR_STATUS["warning"]
    else:
        kolor = KOLOR_STATUS["ok"]

    styl_zasiegu = dict(size=FS["title"], weight="bold", color=kolor, no_wrap=True)
    if zasieg is None:
        tekst_zasiegu = ft.Text("—", **styl_zasiegu)
    else:
        j = jednostka_dystansu()
        tekst_zasiegu = scena.liczba(db.dystans_z_km(zasieg, j), lambda v: f"{formatuj_liczba(v, 0)} {j}",
                                     **styl_zasiegu)

    gorny = ft.Row([
        ft.Row([
            ft.Icon(ft.Icons.LOCAL_GAS_STATION, size=16, color=kolor),
            ft.Text("Szacowany zasięg", size=FS["label"], color=ft.Colors.ON_SURFACE_VARIANT,
                    expand=True, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
        ], spacing=6, expand=True),
        tekst_zasiegu,
    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

    elementy = [gorny]
    if procent is not None:
        elementy.append(scena.wskaznik(ft.ProgressBar(
            value=max(0.0, min(1.0, procent / 100)), color=kolor,
            bgcolor=tlo_toru(page),
            height=8, border_radius=4,
        )))

    # Prognoza najbliższego tankowania — to samo tempo (km/dzień), co przy
    # terminach podzespołów. Pokazujemy ją też w kompaktowym kafelku kokpitu:
    # to ta liczba odpowiada na pytanie „zdążę bez tankowania?”, nie sam procent baku.
    dni_do_pustego = dane.get("dni_do_pustego")
    if dni_do_pustego is not None:
        if dni_do_pustego <= 0:
            opis_dni = "dziś"
        elif dni_do_pustego == 1:
            opis_dni = "jutro"
        else:
            opis_dni = f"za około {dni_do_pustego} dni"
        kolor_prognozy = (
            KOLOR_STATUS["critical"] if dni_do_pustego <= 2
            else KOLOR_STATUS["warning"] if dni_do_pustego <= 5
            else ft.Colors.ON_SURFACE_VARIANT
        )
        data_pustego = dane.get("data_pustego")
        elementy.append(ft.Row([
            ft.Icon(ft.Icons.EVENT_BUSY, size=13, color=kolor_prognozy),
            ft.Text(
                f"Przy Twoim tempie zabraknie paliwa {opis_dni}"
                + (f" ({data_pustego})" if data_pustego else "") + ".",
                size=FS["caption"], weight="bold" if dni_do_pustego <= 5 else "normal",
                color=kolor_prognozy, expand=True,
            ),
        ], spacing=5))

    if not kompaktowy:
        czesci = []
        if dane.get("pojemnosc"):
            czesci.append(f"bak {formatuj_liczba(dane['pojemnosc'], 0)} l")
        if dane.get("pozostalo_jednostek") is not None:
            czesci.append(f"~{formatuj_liczba(dane['pozostalo_jednostek'], 1)} l w baku")
        if dane.get("zasieg_pelny"):
            czesci.append(f"pełny bak ≈ {formatuj_dystans(dane['zasieg_pelny'])}")
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
        padding=SPACING["lg"],
        **powierzchnia(page, "karta", cien="md"),
        content=ft.Column([
            ft.Row([
                ft.Icon(ikona, size=18, color=kolor),
                ft.Text(tytul, size=FS["title"], weight="bold", expand=True),
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
    j = jednostka_dystansu()
    xy = [((w["data_obj"] - start).days, db.dystans_z_km(w["przebieg"], j), w["zrodlo"]) for w in punkty]
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
            tooltip=f"{punkty[i]['data']}\n{formatuj_liczba(y, 0)} {j}\n{punkty[i]['etykieta_zrodla']}",
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


# ---------------------- KOSZT SKUMULOWANY ----------------------
# Jedyny wykres w aplikacji, którego nie da się oszukać uśrednianiem: słupek
# miesięczny chowa przegląd za cztery tysiące między tankowaniami, a krzywa
# narastająca zostawia go na sobie na zawsze.

# Sufit punktów na krzywej. Pięć lat codziennych wpisów to prawie dwa tysiące
# punktów RAZY cztery serie — na telefonie znać to od razu przy przewijaniu,
# a krzywa narastająca jest na tyle gładka, że po przerzedzeniu wygląda
# identycznie. Dni z wyróżnionym wydatkiem zostają zawsze.
MAKS_PUNKTOW_KRZYWEJ = 180

# Kolory serii są TE SAME, co kafelki „Podsumowania kosztów” — paliwo
# niebieskie, serwis pomarańczowy, inne zielone. Inny zestaw na wykresie
# kazałby uczyć się legendy drugi raz.
KOLORY_SERII_KOSZTU = {
    "paliwo": ft.Colors.BLUE_700,
    # paleta: tożsamość — kolor kategorii kosztu, nie stanu
    "serwis": ft.Colors.ORANGE_700,
    # paleta: tożsamość — kolor kategorii kosztu, nie stanu
    "inne": ft.Colors.GREEN_700,
}


def _kwota_osi(wartosc):
    """Podpis osi pionowej: tysiące skracamy, bo pełna kwota z separatorem nie
    mieści się w szerokości podpisu na telefonie."""
    if abs(wartosc) >= 10000:
        return f"{formatuj_liczba(wartosc / 1000, 0)} tys."
    return formatuj_liczba(wartosc, 0)


def _kropka_legendy(kolor, tekst, obwodka=False):
    znacznik = ft.Container(
        width=9, height=9, border_radius=RADIUS["pill"],
        bgcolor=None if obwodka else kolor,
        border=ft.Border.all(2, kolor) if obwodka else None,
    )
    return ft.Row([znacznik, podpis(tekst)], spacing=5, tight=True)


def wykres_kosztu_skumulowanego(page: ft.Page, dane, wysokosc=210, od_daty=None):
    """Krzywa sumy narastającej: gruba „Razem” na pierwszym planie, pod nią trzy
    cienkie serie kategorii, a na niej znaczniki większych wydatków.

    Oś X to DNI od startu, a nie numer wpisu — dwa tankowania w jednym tygodniu
    i pół roku ciszy mają na tej krzywej wyglądać INACZEJ, bo właśnie po to się
    na nią patrzy.

    `od_daty` przycina WIDOK, nie rachunek: wartości zostają narastające od
    zakupu, więc przy krótkim zakresie krzywa wchodzi w kadr wysoko, a nie
    zaczyna się od zera. Inaczej „ostatnie 3 miesiące” pokazywałyby trzeci
    wykres wydatków miesięcznych, a nie sumę narastającą."""
    punkty = list(dane.get("punkty") or [])
    dni_wyroznione = {w["dzien"] for w in (dane.get("wyroznione") or [])}

    if od_daty:
        w_kadrze = [p for p in punkty if p["data"] >= od_daty]
        # Ostatni punkt sprzed granicy zostaje, żeby krzywa wchodziła z lewej
        # krawędzi zamiast zaczynać się w powietrzu nad nią.
        przed = [p for p in punkty if p["data"] < od_daty]
        if przed:
            w_kadrze.insert(0, przed[-1])
        punkty = w_kadrze

    if len(punkty) < 2:
        return None

    if len(punkty) > MAKS_PUNKTOW_KRZYWEJ:
        krok = -(-len(punkty) // MAKS_PUNKTOW_KRZYWEJ)
        ostatni = len(punkty) - 1
        punkty = [p for i, p in enumerate(punkty)
                  if i % krok == 0 or i == ostatni or p["dzien"] in dni_wyroznione]

    min_x, maks_x = punkty[0]["dzien"], punkty[-1]["dzien"]
    if maks_x <= min_x:
        maks_x = min_x + 1
    wartosci = [p["razem"] for p in punkty]
    min_y, maks_y = min(wartosci), max(wartosci)
    zapas = max((maks_y - min_y) * 0.10, 1.0)

    wyroznione = {w["dzien"]: w for w in (dane.get("wyroznione") or [])
                  if min_x <= w["dzien"] <= maks_x}

    def punkt_razem(p):
        wyroznik = wyroznione.get(p["dzien"])
        if not wyroznik:
            return fc.LineChartDataPoint(p["dzien"], p["razem"])
        return fc.LineChartDataPoint(
            p["dzien"], p["razem"],
            point=fc.ChartCirclePoint(color=KOLOR_STATUS["accent"], radius=4.5, stroke_width=0),
            tooltip=(f"{wyroznik['data'].strftime('%d.%m.%Y')}\n{wyroznik['opis']}\n"
                     f"+{formatuj_liczba(wyroznik['kwota'])} {symbol_waluty()}\n"
                     f"razem {formatuj_liczba(p['razem'])} {symbol_waluty()}"),
        )

    serie = [
        fc.LineChartData(
            points=[fc.LineChartDataPoint(p["dzien"], p[kategoria]) for p in punkty],
            stroke_width=1.5, color=kolor, curved=False, rounded_stroke_cap=True,
        )
        for kategoria, kolor in KOLORY_SERII_KOSZTU.items()
    ]
    serie.append(fc.LineChartData(
        points=[punkt_razem(p) for p in punkty],
        stroke_width=3, color=ft.Colors.PRIMARY, curved=False, rounded_stroke_cap=True,
        below_line_bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.PRIMARY),
    ))

    # Trzy podpisy na osi czasu — więcej nachodzi na siebie na szerokości
    # telefonu, a przy krzywej narastającej i tak liczy się kształt, nie odczyt
    # konkretnego dnia.
    indeksy = sorted({0, len(punkty) // 2, len(punkty) - 1})
    etykiety_x = [
        fc.ChartAxisLabel(
            value=punkty[i]["dzien"],
            label=ft.Text(punkty[i]["data"].strftime("%m.%y"), size=9,
                          color=ft.Colors.ON_SURFACE_VARIANT),
        )
        for i in indeksy
    ]

    wykres = ft.Container(
        height=wysokosc,
        padding=ft.Padding(0, SPACING["sm"], SPACING["sm"], 0),
        content=fc.LineChart(
            data_series=serie,
            horizontal_grid_lines=fc.ChartGridLines(
                interval=max(1, int((maks_y - min_y) / 3) or 1),
                color=ft.Colors.with_opacity(0.10, ft.Colors.ON_SURFACE), width=1,
            ),
            left_axis=fc.ChartAxis(
                labels=[
                    fc.ChartAxisLabel(
                        value=w,
                        label=ft.Text(_kwota_osi(w), size=9, color=ft.Colors.ON_SURFACE_VARIANT),
                    )
                    for w in (min_y, (min_y + maks_y) / 2, maks_y)
                ],
                label_size=46, title_size=0,
            ),
            bottom_axis=fc.ChartAxis(labels=etykiety_x, label_size=22, title_size=0),
            right_axis=fc.ChartAxis(show_labels=False, label_size=0, title_size=0),
            top_axis=fc.ChartAxis(show_labels=False, label_size=0, title_size=0),
            min_x=min_x, max_x=maks_x,
            min_y=max(0, min_y - zapas), max_y=maks_y + zapas,
            interactive=True,
            expand=True,
        ),
    )

    legenda = [_kropka_legendy(ft.Colors.PRIMARY, "Razem")]
    legenda += [_kropka_legendy(kolor, db.KATEGORIE_BUDZETU.get(kat, kat))
                for kat, kolor in KOLORY_SERII_KOSZTU.items()]
    if wyroznione:
        legenda.append(_kropka_legendy(KOLOR_STATUS["accent"], "większy wydatek", obwodka=True))

    return ft.Column([
        wykres,
        ft.Row(legenda, spacing=SPACING["md"], wrap=True, run_spacing=4),
    ], spacing=SPACING["sm"])


def karta_kosztu_skumulowanego(page: ft.Page, dane, od_daty=None, wysokosc=210):
    """Cała karta: nagłówek z trzema liczbami, krzywa, legenda i przypisy.

    Liczby w nagłówku są ZAWSZE od zakupu, niezależnie od wybranego zakresu
    czasu — „ile mnie to kosztowało” nie jest pytaniem o ostatni kwartał."""
    wykres = wykres_kosztu_skumulowanego(page, dane, wysokosc=wysokosc, od_daty=od_daty)
    # Sama cena zakupu to POZIOMA kreska od dnia zakupu do dzisiaj — narastać
    # nie ma z czego, dopóki nie ma ani jednego wydatku.
    if wykres is None or not dane.get("wydatki"):
        return ft.Container(
            padding=SPACING["lg"],
            **powierzchnia(page, "karta", cien="md"),
            content=podpis(
                "Za mało danych na krzywą narastającą — potrzeba wpisów kosztowych. "
                "Datę, cenę i przebieg przy zakupie ustawia się w danych pojazdu."
            ),
        )

    od_kiedy = ("od zakupu" if dane.get("czy_od_zakupu") else "od pierwszego wpisu")
    liczby = [ft.Column([etykieta(f"Razem {od_kiedy}"),
                         wartosc(f"{formatuj_liczba(dane['suma'])} {symbol_waluty()}")],
                        spacing=2, expand=True)]
    if dane.get("koszt_dzien"):
        liczby.append(ft.Column([etykieta("Na dzień"),
                                 wartosc(f"{formatuj_liczba(dane['koszt_dzien'])} {symbol_waluty()}")],
                                spacing=2, expand=True))
    if dane.get("koszt_km"):
        liczby.append(ft.Column([etykieta(f"Na {db.slowo_dystansu('biernik')}"),
                                 wartosc(f"{formatuj_liczba(db.na_jednostke_dystansu(dane['koszt_km']), 2)} "
                                         f"{symbol_waluty()}")],
                                spacing=2, expand=True))

    przypisy = []
    if dane.get("z_cena_zakupu"):
        przypisy.append(podpis(
            f"W tym cena zakupu {formatuj_liczba(dane['cena_zakupu'])} {symbol_waluty()} "
            f"— krzywa startuje od niej, a nie od zera."))
    sprzedaz = dane.get("sprzedaz")
    if sprzedaz:
        tekst = f"Rachunek zamknięty {sprzedaz['data'].strftime('%d.%m.%Y')} — dniem sprzedaży"
        if sprzedaz.get("po_odliczeniu") is not None:
            tekst += (f". Po odliczeniu ceny sprzedaży "
                      f"({formatuj_liczba(sprzedaz['cena'])} {symbol_waluty()}) zostaje "
                      f"{formatuj_liczba(sprzedaz['po_odliczeniu'])} {symbol_waluty()}")
        przypisy.append(podpis(tekst + "."))

    return ft.Container(
        padding=SPACING["lg"],
        **powierzchnia(page, "karta", cien="md"),
        content=ft.Column(
            [ft.Row(liczby, spacing=SPACING["md"]), wykres] + przypisy,
            spacing=SPACING["md"],
        ),
    )


# ---------------------- KOSZT NA 1000 KM W OKNIE ----------------------
# Suma roczna rośnie także wtedy, gdy po prostu jeździsz więcej — koszt na
# dystans nie, bo dzieli wydatek przez to, co się za niego dostało. Dlatego
# to jest krzywa, na której widać moment, w którym auto zaczyna drożeć.

OKNA_CZASU = [("6 mies.", 6), ("Rok", 12), ("2 lata", 24)]

# Od ilu procent nad średnią życiową krzywa znaczy „drożeje”, a nie „szum”.
# Pięć procent mieści się w jednym droższym przeglądzie, piętnaście już nie.
PROG_DROZENIA = 15.0


def pasek_okna_kroczacego(page: ft.Page, state):
    """Długość okna kroczącego nad wykresem kosztu na 1000 km.

    To NIE jest pasek zakresu widoku: chipy zmieniają tu sposób LICZENIA
    każdego punktu, a nie wycinek osi. Oś pokazuje zawsze całą historię, dla
    której okno jest pełne — przy krótszym oknie krzywa jest dłuższa i bardziej
    nerwowa, przy dłuższym krótsza i gładsza."""
    auto_id = getattr(state, "auto_id", None)
    aktualne = db.pobierz_okno_kroczace(auto_id)

    def wybierz(miesiace):
        db.zapisz_okno_kroczace(auto_id, miesiace)
        odswiez_ekran(page)

    return _pigulka_chipow(
        page, OKNA_CZASU, aktualne, wybierz,
        lambda m: f"Licz każdy punkt z ostatnich {m} miesięcy",
    )


def krzywa_1000_w_jednostce(dane, jednostka=None):
    """Wynik db.koszt_na_1000km przeliczony na 1000 jednostek z Ustawień.

    Kopia z kluczem „jednostka” — drugie wywołanie na tym samym wyniku niczego
    już nie mnoży, więc karta, wykres i kafelek mogą wołać ją bez umawiania się,
    kto przelicza. Koszty „razem” (suma w oknie) i procenty zostają, bo nie są
    liczone na dystans; kilometry w oknie zamieniają się w mile."""
    j = jednostka_dystansu() if jednostka is None else jednostka
    if not dane:
        return dane
    if dane.get("jednostka", "km") == j:
        return dict(dane, jednostka=j)

    bez_zmian = {"rok", "miesiac", "klucz", "razem"}

    def punkt(p):
        nowy = {}
        for klucz, v in p.items():
            if klucz == "km":
                nowy[klucz] = db.dystans_z_km(v, j)
            elif klucz in bez_zmian or not isinstance(v, (int, float)):
                nowy[klucz] = v
            else:
                nowy[klucz] = db.na_jednostke_dystansu(v, j)
        return nowy

    szczyt = dane.get("szczyt")
    return dict(
        dane, jednostka=j,
        punkty=[punkt(p) for p in dane.get("punkty") or []],
        iskra=[db.na_jednostke_dystansu(v, j) for v in dane.get("iskra") or []],
        biezacy=db.na_jednostke_dystansu(dane.get("biezacy"), j),
        srednia_zyciowa=db.na_jednostke_dystansu(dane.get("srednia_zyciowa"), j),
        szczyt=punkt(szczyt) if szczyt else szczyt,
    )


def wykres_kosztu_1000km(page: ft.Page, dane, wysokosc=210):
    """Krzywa kosztu na 1000 km w oknie kroczącym: gruba „Razem”, trzy cienkie
    serie kategorii, przerywana linia średniej życiowej i znacznik w szczycie.

    Oś pionowa zaczyna się w ZERZE, a nie tuż pod najniższym punktem. Obcięta
    oś robi z dziesięcioprocentowej zmiany urwisko — a to jest wykres, na
    którego podstawie sprzedaje się auto."""
    dane = krzywa_1000_w_jednostce(dane) or {}
    j = dane.get("jednostka", "km")
    punkty = dane.get("punkty") or []
    if len(punkty) < 2:
        return None

    wartosci = [p["koszt"] for p in punkty]
    srednia = dane.get("srednia_zyciowa")
    maks_y = max(wartosci + ([srednia] if srednia else [])) * 1.12 or 1.0
    szczyt = dane.get("szczyt") or {}
    ostatni_x = len(punkty) - 1

    def punkt_razem(i, p):
        wspolne = {"tooltip": (f"{p['miesiac']:02d}/{p['rok']}\n"
                               f"{formatuj_liczba(p['koszt'])} {symbol_waluty()} / 1000 {j}\n"
                               f"{formatuj_liczba(p['km'], 0)} {j} w oknie")}
        if p["klucz"] == szczyt.get("klucz"):
            return fc.LineChartDataPoint(
                i, p["koszt"],
                point=fc.ChartCirclePoint(color=KOLOR_STATUS["accent"], radius=4.5, stroke_width=0),
                **wspolne,
            )
        return fc.LineChartDataPoint(i, p["koszt"], **wspolne)

    serie = [
        fc.LineChartData(
            points=[fc.LineChartDataPoint(i, p[kategoria]) for i, p in enumerate(punkty)],
            stroke_width=1.5, color=kolor, curved=False, rounded_stroke_cap=True,
        )
        for kategoria, kolor in KOLORY_SERII_KOSZTU.items()
    ]
    if srednia:
        serie.append(fc.LineChartData(
            points=[fc.LineChartDataPoint(0, srednia), fc.LineChartDataPoint(ostatni_x, srednia)],
            stroke_width=1.5, color=ft.Colors.ON_SURFACE_VARIANT,
            dash_pattern=[6, 4], curved=False,
        ))
    serie.append(fc.LineChartData(
        points=[punkt_razem(i, p) for i, p in enumerate(punkty)],
        stroke_width=3, color=ft.Colors.PRIMARY, curved=False, rounded_stroke_cap=True,
        below_line_bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.PRIMARY),
    ))

    krok = krok_etykiet_osi(len(punkty))
    etykiety_x = [
        fc.ChartAxisLabel(
            value=i,
            label=ft.Text(f"{p['miesiac']:02d}/{str(p['rok'])[2:]}", size=9,
                          color=ft.Colors.ON_SURFACE_VARIANT),
        )
        for i, p in enumerate(punkty)
        if i % krok == 0 or i == ostatni_x
    ]

    wykres = ft.Container(
        height=wysokosc,
        padding=ft.Padding(0, SPACING["sm"], SPACING["sm"], 0),
        content=fc.LineChart(
            data_series=serie,
            horizontal_grid_lines=fc.ChartGridLines(
                interval=max(1, int(maks_y / 4) or 1),
                color=ft.Colors.with_opacity(0.10, ft.Colors.ON_SURFACE), width=1,
            ),
            left_axis=fc.ChartAxis(
                labels=[
                    fc.ChartAxisLabel(
                        value=w,
                        label=ft.Text(_kwota_osi(w), size=9, color=ft.Colors.ON_SURFACE_VARIANT),
                    )
                    for w in (0, maks_y / 2, maks_y)
                ],
                label_size=46, title_size=0,
            ),
            bottom_axis=fc.ChartAxis(labels=etykiety_x, label_size=22, title_size=0),
            right_axis=fc.ChartAxis(show_labels=False, label_size=0, title_size=0),
            top_axis=fc.ChartAxis(show_labels=False, label_size=0, title_size=0),
            min_x=0, max_x=ostatni_x, min_y=0, max_y=maks_y,
            interactive=True,
            expand=True,
        ),
    )

    legenda = [_kropka_legendy(ft.Colors.PRIMARY, "Razem")]
    legenda += [_kropka_legendy(kolor, db.KATEGORIE_BUDZETU.get(kat, kat))
                for kat, kolor in KOLORY_SERII_KOSZTU.items()]
    if srednia:
        legenda.append(_kropka_legendy(ft.Colors.ON_SURFACE_VARIANT, "średnia życiowa", obwodka=True))
    if szczyt:
        legenda.append(_kropka_legendy(KOLOR_STATUS["accent"], "najdroższe okno", obwodka=True))

    return ft.Column([
        wykres,
        ft.Row(legenda, spacing=SPACING["md"], wrap=True, run_spacing=4),
    ], spacing=SPACING["sm"])


def karta_kosztu_1000km(page: ft.Page, dane, wysokosc=210):
    """Cała karta: bieżące okno wielką liczbą, chip zmiany rok do roku, krzywa
    i dwa zdania przypisu — najdroższe okno i średnia życiowa."""
    dane = krzywa_1000_w_jednostce(dane) or {}
    j = dane.get("jednostka", "km")
    wykres = wykres_kosztu_1000km(page, dane, wysokosc=wysokosc)
    if wykres is None:
        return ft.Container(
            padding=SPACING["lg"],
            **powierzchnia(page, "karta", cien="md"),
            content=podpis(
                "Za mało danych na koszt w oknie kroczącym — potrzeba odczytów licznika "
                "i wydatków z co najmniej dwóch pełnych okien. Krótsze okno (6 mies.) "
                "wystarcza wcześniej."
            ),
        )

    naglowek = [
        ft.Column([
            etykieta(f"Ostatnie {dane['okno']} mies."),
            wartosc(f"{formatuj_liczba(dane['biezacy'])} {symbol_waluty()} / 1000 {j}"),
        ], spacing=2, expand=True),
    ]
    if dane.get("zmiana_rdr") is not None:
        naglowek.append(znacznik_trendu(dane["zmiana_rdr"], wzrost_zly=True))

    przypisy = []
    srednia = dane.get("srednia_zyciowa")
    if srednia:
        nad = ((dane["biezacy"] - srednia) / srednia * 100) if srednia > 0 else 0
        if nad >= PROG_DROZENIA:
            ocena = f"o {formatuj_liczba(nad, 0)}% DROŻEJ niż średnia życiowa"
        elif nad <= -PROG_DROZENIA:
            ocena = f"o {formatuj_liczba(abs(nad), 0)}% taniej niż średnia życiowa"
        else:
            ocena = "w okolicach średniej życiowej"
        przypisy.append(podpis(
            f"Średnia życiowa: {formatuj_liczba(srednia)} {symbol_waluty()} / 1000 {j} — "
            f"bieżące okno jest {ocena}."))
    szczyt = dane.get("szczyt")
    if szczyt and szczyt.get("klucz"):
        przypisy.append(podpis(
            f"Najdroższe okno kończyło się w {szczyt['miesiac']:02d}/{szczyt['rok']}: "
            f"{formatuj_liczba(szczyt['koszt'])} {symbol_waluty()} / 1000 {j}."))

    return ft.Container(
        padding=SPACING["lg"],
        **powierzchnia(page, "karta", cien="md"),
        content=ft.Column(
            [ft.Row(naglowek, spacing=SPACING["md"],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER), wykres] + przypisy,
            spacing=SPACING["md"],
        ),
    )


# ---------------------- ROK DO ROKU NA JEDNEJ OSI ----------------------
# Zdanie „drożej o 23%” i liczba w podsumowaniu roku mówią O ILE. Dwie krzywe
# na jednej osi miesięcy mówią OD KIEDY — a to zwykle wskazuje zdarzenie:
# miesiąc, w którym zaczął się abonament albo wypadł drogi serwis.

POSTACIE_RDR = [("Narastająco", True), ("Miesięcznie", False)]


def _chip_maly(tekst, aktywny, on_click, tooltip=None):
    """Chip wyboru w pasku przewijanym — własna szerokość, więc nie rozpycha
    się na cały pasek (patrz uwaga przy `pasek_zawijany`)."""
    return ft.Container(
        height=28, padding=ft.Padding(12, 0, 12, 0),
        border_radius=RADIUS["pill"], ink=True,
        bgcolor=ft.Colors.PRIMARY if aktywny else ft.Colors.TRANSPARENT,
        border=None if aktywny else ft.Border.all(1, ft.Colors.OUTLINE),
        animate=ft.Animation(180, ft.AnimationCurve.EASE_OUT),
        tooltip=tooltip,
        on_click=on_click,
        content=ft.Row([ft.Text(
            tekst, size=FS["caption"], weight="bold" if aktywny else "normal",
            color=ft.Colors.ON_PRIMARY if aktywny else ft.Colors.ON_SURFACE_VARIANT,
            no_wrap=True,
        )], tight=True),
    )


def pasek_lat_rdr(page: ft.Page, state):
    """Wybór roku nad wykresem rok do roku. Cztery najnowsze lata z danymi —
    dalej wstecz i tak nie ma z czym porównywać, a pigułka nie mieści więcej."""
    lata = db.lata_z_danymi(getattr(state, "auto_id", None))
    if len(lata) < 2:
        return ft.Container()
    wybrany = getattr(state, "rdr_rok", None) or lata[0]

    def wybierz(rok):
        state.rdr_rok = rok
        odswiez_ekran(page)

    return _pigulka_chipow(page, [(str(r), r) for r in lata[:4]], wybrany, wybierz,
                           lambda r: f"Porównaj {r} z rokiem {r - 1}")


def wykres_rok_do_roku(page: ft.Page, dane, wysokosc=210):
    """Dwie krzywe na jednej osi miesięcy: wybrany rok grubą linią, poprzedni
    przerywaną. Między nimi pionowe słupki różnicy — dzięki nim nie trzeba
    czytać osi, żeby zobaczyć, gdzie i jak bardzo lata się rozchodzą.

    Oś pionowa zaczyna się w ZERZE. Przy dwóch krzywych obcięta oś kłamie
    podwójnie: nie tylko wyolbrzymia zmianę, ale i odległość między latami."""
    biezacy = list(dane.get("biezacy") or [])
    poprzedni = list(dane.get("poprzedni") or [])
    znane_b = [w for w in biezacy if w is not None]
    znane_p = [w for w in poprzedni if w is not None]
    if len(znane_b) < 2 or len(znane_p) < 2:
        return None

    maks_y = (max(znane_b + znane_p) * 1.12) or 1.0
    rozjazd = dane.get("miesiac_rozjazdu")

    def punkty(seria, z_rozjazdem=False):
        wynik = []
        for i, w in enumerate(seria):
            if w is None:
                continue
            if z_rozjazdem and rozjazd == i + 1:
                wynik.append(fc.LineChartDataPoint(
                    i, w,
                    point=fc.ChartCirclePoint(color=KOLOR_STATUS["accent"], radius=5, stroke_width=0),
                    tooltip=f"{MIESIACE_NAZWY[i]}\nod tego miesiąca lata się rozchodzą",
                ))
            else:
                wynik.append(fc.LineChartDataPoint(i, w, tooltip=f"{MIESIACE_NAZWY[i]}\n{_kwota_osi(w)}"))
        return wynik

    # Słupki różnicy rysujemy PIERWSZE, żeby leżały pod krzywymi. Każdy miesiąc
    # to osobna dwupunktowa seria — wykresy liniowe Fleta nie umieją wypełnić
    # obszaru MIĘDZY dwiema krzywymi, a pionowa kreska mówi dokładnie to samo.
    kolor_gorszy = KOLOR_STATUS["critical"] if dane.get("wzrost_zly") else ft.Colors.PRIMARY
    kolor_lepszy = KOLOR_STATUS["ok"] if dane.get("wzrost_zly") else ft.Colors.PRIMARY
    serie = []
    for i in range(12):
        a, b = biezacy[i], poprzedni[i]
        if a is None or b is None or a == b:
            continue
        kolor = kolor_gorszy if a > b else kolor_lepszy
        serie.append(fc.LineChartData(
            points=[fc.LineChartDataPoint(i, min(a, b)), fc.LineChartDataPoint(i, max(a, b))],
            stroke_width=7, color=ft.Colors.with_opacity(0.18, kolor), curved=False,
        ))

    serie.append(fc.LineChartData(
        points=punkty(poprzedni), stroke_width=2, color=ft.Colors.ON_SURFACE_VARIANT,
        dash_pattern=[6, 4], curved=False, rounded_stroke_cap=True,
    ))
    serie.append(fc.LineChartData(
        points=punkty(biezacy, z_rozjazdem=True), stroke_width=3, color=ft.Colors.PRIMARY,
        curved=False, rounded_stroke_cap=True,
    ))

    etykiety_x = [
        fc.ChartAxisLabel(
            value=i,
            label=ft.Text(MIESIACE_NAZWY[i][:3], size=9, color=ft.Colors.ON_SURFACE_VARIANT),
        )
        for i in range(0, 12, 2)
    ]

    wykres = ft.Container(
        height=wysokosc,
        padding=ft.Padding(0, SPACING["sm"], SPACING["sm"], 0),
        content=fc.LineChart(
            data_series=serie,
            horizontal_grid_lines=fc.ChartGridLines(
                interval=max(1, int(maks_y / 4) or 1),
                color=ft.Colors.with_opacity(0.10, ft.Colors.ON_SURFACE), width=1,
            ),
            left_axis=fc.ChartAxis(
                labels=[
                    fc.ChartAxisLabel(
                        value=w,
                        label=ft.Text(_kwota_osi(w), size=9, color=ft.Colors.ON_SURFACE_VARIANT),
                    )
                    for w in (0, maks_y / 2, maks_y)
                ],
                label_size=46, title_size=0,
            ),
            bottom_axis=fc.ChartAxis(labels=etykiety_x, label_size=22, title_size=0),
            right_axis=fc.ChartAxis(show_labels=False, label_size=0, title_size=0),
            top_axis=fc.ChartAxis(show_labels=False, label_size=0, title_size=0),
            min_x=0, max_x=11, min_y=0, max_y=maks_y,
            interactive=True,
            expand=True,
        ),
    )

    legenda = [
        _kropka_legendy(ft.Colors.PRIMARY, str(dane["rok"])),
        _kropka_legendy(ft.Colors.ON_SURFACE_VARIANT, str(dane["rok_poprzedni"]), obwodka=True),
    ]
    if len(serie) > 2:
        legenda.append(_kropka_legendy(kolor_gorszy, "różnica"))
    if rozjazd:
        legenda.append(_kropka_legendy(KOLOR_STATUS["accent"], "rozjazd", obwodka=True))

    return ft.Column([
        wykres,
        ft.Row(legenda, spacing=SPACING["md"], wrap=True, run_spacing=4),
    ], spacing=SPACING["sm"])


def _jednostka_rdr(dane):
    # Dane przychodzą już w jednostce z Ustawień (db.koszty_rok_do_roku).
    j = jednostka_dystansu()
    return (f" {symbol_waluty()}/1000 {j}" if dane["wielkosc"] == "koszt1000"
            else (f" {j}" if dane["jednostka"] == "km" else f" {symbol_waluty()}"))


def karta_rok_do_roku(page: ft.Page, state, rok=None, wysokosc=210):
    """Cała karta: chipy wielkości, przełącznik postaci krzywej, dwie krzywe
    i zdanie o miesiącu, w którym lata się rozeszły.

    `rok` podaje ekran, który ma własny selektor roku (Rok w pigułce); bez
    niego rok bierze się ze stanu i wybiera go pasek nad kartą."""
    wielkosc = getattr(state, "rdr_wielkosc", "razem")
    narastajaco = bool(getattr(state, "rdr_narastajaco", True))
    dane = db.koszty_rok_do_roku(
        getattr(state, "auto_id", None),
        rok=rok or getattr(state, "rdr_rok", None),
        wielkosc=wielkosc, narastajaco=narastajaco,
    )

    def wybierz_wielkosc(klucz):
        state.rdr_wielkosc = klucz
        odswiez_ekran(page)

    def wybierz_postac(czy_narastajaco):
        state.rdr_narastajaco = czy_narastajaco
        odswiez_ekran(page)

    chipy = ft.Row(
        [
            _chip_maly(opis, klucz == dane["wielkosc"],
                       lambda e, k=klucz: wybierz_wielkosc(k))
            for klucz, opis in db.etykiety_wielkosci_rdr().items()
        ],
        scroll=ft.ScrollMode.ADAPTIVE, spacing=8,
    )
    przelacznik = _pigulka_chipow(
        page, POSTACIE_RDR, narastajaco, wybierz_postac,
        lambda czy: ("Suma od stycznia — widać miesiąc, w którym lata się rozeszły"
                     if czy else "Wartości miesięczne — widać pojedyncze skoki"),
    )

    wykres = wykres_rok_do_roku(page, dane, wysokosc=wysokosc)
    if wykres is None:
        tresc = [podpis(
            f"Brak danych do porównania {dane['rok']} z rokiem {dane['rok_poprzedni']} "
            f"w tej wielkości — potrzeba wpisów w obu latach."
        )]
    else:
        jedn = _jednostka_rdr(dane)
        naglowek = [ft.Column([
            etykieta(f"{dane['etykieta']} • {dane['rok']} kontra {dane['rok_poprzedni']}"),
            wartosc(_tekst_roznicy(dane, jedn)),
        ], spacing=2, expand=True)]
        if dane.get("zmiana_proc") is not None:
            naglowek.append(znacznik_trendu(dane["zmiana_proc"], wzrost_zly=dane["wzrost_zly"]))

        przypisy = []
        if dane.get("miesiac_rozjazdu"):
            nazwa_mc = MIESIACE_MIEJSCOWNIK[dane["miesiac_rozjazdu"] - 1]
            przypisy.append(podpis(
                f"Rozjechało się w {nazwa_mc}: wtedy różnica między latami urosła najmocniej. "
                f"Wcześniej oba lata szły niemal równo."))
        elif dane.get("roznica_koncowa"):
            przypisy.append(podpis(
                "Różnica narastała stopniowo — nie ma jednego miesiąca, który by ją zrobił."))
        if dane.get("niepelny"):
            przypisy.append(podpis(
                f"Rok w toku: porównanie obejmuje styczeń–{MIESIACE_NAZWY[dane['ostatni_miesiac'] - 1].lower()} "
                f"po obu stronach."))
        tresc = [ft.Row(naglowek, spacing=SPACING["md"],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER), wykres] + przypisy

    return ft.Container(
        padding=SPACING["lg"],
        **powierzchnia(page, "karta", cien="md"),
        content=ft.Column([chipy, przelacznik] + tresc, spacing=SPACING["md"]),
    )


def _tekst_roznicy(dane, jedn):
    """Nagłówek karty: różnica w jednostkach wielkości, słowami."""
    roznica = dane.get("roznica_koncowa")
    if roznica is None:
        return "—"
    if abs(roznica) < 0.005:
        return "bez zmian wobec poprzedniego roku"
    kierunek = "więcej" if roznica > 0 else "mniej"
    return f"{formatuj_liczba(abs(roznica))}{jedn} {kierunek}"


def znacznik_trendu(zmiana_proc, prog=5, wzrost_zly=True, rozmiar=11,
                    tekst_bez_trendu=None, ikona_bez_trendu=None):
    """Mały „chip” trendu: strzałka + procent zmiany. `wzrost_zly=True` znaczy,
    że rosnąca wartość jest zła (koszty, spalanie) i dostaje kolor czerwony.
    Zwraca ft.Row gotowy do wstawienia pod wartością na kafelku.

    `tekst_bez_trendu` i `ikona_bez_trendu` podmieniają wariant neutralny, gdy
    zmiany NIE DA SIĘ policzyć — kokpit mówi wtedy „Za wcześnie na trend”
    z ikoną informacji, zamiast udawać płaski trend napisem „Brak trendu”."""
    try:
        zmiana = float(zmiana_proc)
    except (TypeError, ValueError):
        return ft.Row([
            ft.Icon(ikona_bez_trendu or ft.Icons.TRENDING_FLAT, size=13,
                    color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Text(tekst_bez_trendu or "Brak trendu", size=rozmiar,
                    color=ft.Colors.ON_SURFACE_VARIANT, no_wrap=True),
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

    # ŚWIADOMIE bez expand: ten wiersz trafia jako element do INNEGO wiersza
    # (stopka kafelka kokpitu), gdzie szerokość jest nieograniczona — expand
    # w takim miejscu wywala układ Fluttera. Tekst to zawsze krótkie „−12%”.
    return ft.Row([
        ft.Icon(ikona, size=13, color=kolor),
        ft.Text(tekst, size=rozmiar, color=kolor, no_wrap=True),
    ], spacing=4)


def pasek_postepu(etykieta_lewa, etykieta_prawa, procent, kolor, wysokosc=8, scena=None):
    """Wspólny 'wiersz postępu': etykieta + wartość nad kolorowym ProgressBar.
    procent: 0.0-1.0 (spoza zakresu jest przycinane). Wydzielone z _pasek_porownania
    (porownanie_view.py). Karta podzespołu w Serwisie ma dwa liczniki naraz, więc
    rysuje je `liczniki_interwalu` niżej — każdy z własnym paskiem.

    `scena` (utils.ScenaWejscia) każe paskowi wypełnić się przy wejściu od zera."""
    scena = scena or ScenaWejscia(wlaczona=False)
    scena.nastepny_wiersz()
    return ft.Column([
        ft.Row([
            # Nazwa po lewej mówi CZEGO dotyczy pasek, liczba po prawej — ILE.
            # Pogrubione były obie, więc nie prowadziły oka nigdzie.
            ft.Text(etykieta_lewa, size=12, color=ft.Colors.ON_SURFACE_VARIANT,
                    expand=True, no_wrap=True),
            ft.Text(etykieta_prawa, size=12, weight="bold", color=kolor)
        ]),
        scena.wskaznik(ft.ProgressBar(
            value=max(0.03, min(1.0, procent)), color=kolor,
            bgcolor=tlo_toru(),
            height=wysokosc, border_radius=4,
        ))
    ], spacing=4)


# Status licznika interwału (db.oblicz_stan_interwalu) -> rola w KOLOR_STATUS.
ROLA_STATUSU_INTERWALU = {"przeterminowane": "critical", "pilne": "warning", "ok": "ok"}


def liczniki_interwalu(stan, scena=None, page=None):
    """Oba liczniki interwału podzespołu obok siebie — kilometry z lewej, czas
    z prawej. Kolejność jest stała, żeby na liście kart oko wiedziało, gdzie
    czego szukać; to, który licznik przyjdzie PIERWSZY, mówi znacznik „najpierw”.
    Przestawiane kolumny kazałyby czytać każdą kartę od nowa.

    Każdy licznik ma własny pasek zużycia interwału w kolorze swojego statusu:
    trzy tysiące kilometrów zapasu wyglądają inaczej obok dwóch tygodni do
    terminu niż obok pół roku. Oba paski ruszają w jednym kroku kaskady, bo to
    jeden wiersz listy. `stan` to wynik db.oblicz_stan_interwalu; bez liczników
    zwraca None."""
    liczniki = [stan[rodzaj] for rodzaj in ("km", "czas") if (stan or {}).get(rodzaj)]
    if not liczniki:
        return None

    scena = scena or ScenaWejscia(wlaczona=False)
    scena.nastepny_wiersz()
    oba = len(liczniki) == 2

    kolumny = []
    for licznik in liczniki:
        czy_km = licznik["rodzaj"] == "km"
        kolor = KOLOR_STATUS[ROLA_STATUSU_INTERWALU.get(licznik["status"], "ok")]
        tekst_wartosci, tekst_podpisu = opis_licznika_na_karte(licznik)

        naglowek = [
            ft.Icon(ft.Icons.SPEED if czy_km else ft.Icons.EVENT, size=14, color=ft.Colors.ON_SURFACE_VARIANT),
            # Luźne rozciągnięcie: etykieta bierze tyle, ile potrzebuje, więc
            # znacznik stoi tuż przy niej — a na wąskim ekranie to ona się
            # zawija, zamiast wypychać znacznik poza kartę.
            etykieta(db.slowo_dystansu("mianownik") if czy_km else "Czas", expand=True, expand_loose=True),
        ]
        if oba and licznik["rodzaj"] == stan.get("pierwsze"):
            naglowek.append(ft.Container(
                padding=ft.Padding(6, 1, 6, 1), border_radius=RADIUS["pill"],
                bgcolor=tlo_odznaki(page),
                content=ft.Text("najpierw", size=10, color=ft.Colors.ON_SURFACE, no_wrap=True),
            ))

        kolumny.append(ft.Column([
            ft.Row(naglowek, spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            wartosc(tekst_wartosci, color=kolor),
            podpis(tekst_podpisu),
            scena.wskaznik(ft.ProgressBar(
                value=max(0.03, min(1.0, licznik["zuzycie"])), color=kolor,
                bgcolor=tlo_toru(page), height=6, border_radius=3,
            )),
        ], spacing=2, expand=True))

    return ft.Row(kolumny, spacing=SPACING["md"], vertical_alignment=ft.CrossAxisAlignment.START)


def heatmapa_aktywnosci(page: ft.Page, daty_zdarzen, tygodnie=53, opis_okresu="ostatni rok"):
    """Heatmapa aktywności w stylu GitHub 'contributions': siatka kwadracików
    (kolumna = tydzień, wiersz = dzień tygodnia) pokazująca, w które dni z
    ostatniego roku pojawiło się jakiekolwiek zdarzenie w dzienniku auta.
    `daty_zdarzen`: dowolna iterowalna surowych dat tekstowych (DD.MM.YYYY);
    kilka zdarzeń tego samego dnia jest sumowanych. Używane przez /timeline.
    `tygodnie` i `opis_okresu` idą z chipów zakresu nad mapą — siatka i jej
    podpis muszą mówić o tym samym okresie, inaczej podpis kłamie."""
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
    # Rok kwadracików nie zmieści się na żadnym telefonie, więc mapa MUSI jechać
    # w bok — dostaje więc widoczny suwak z własnym marginesem, zamiast paska,
    # który pojawiał się dopiero w trakcie przewijania i leżał na komórkach.
    siatka = pasek_przewijany(list(reversed(kolumny_tygodni)), spacing=3,
                              wyrownanie=ft.CrossAxisAlignment.START)

    def kw_legendy(poziom, kolor_bazowy=None):
        return ft.Container(width=WYM, height=WYM, border_radius=3, bgcolor=ft.Colors.with_opacity(poziom, kolor_bazowy or ft.Colors.PRIMARY))

    legenda = ft.Row([
        ft.Text("Mniej", size=10, color=ft.Colors.ON_SURFACE_VARIANT),
        kw_legendy(0.06, ft.Colors.ON_SURFACE), kw_legendy(0.30), kw_legendy(0.55), kw_legendy(0.75), kw_legendy(0.95),
        ft.Text("Więcej", size=10, color=ft.Colors.ON_SURFACE_VARIANT),
    ], spacing=4)

    opis = (f"Najnowszy tydzień po lewej • {aktywne_dni} "
            f"{_odmiana_liczby(aktywne_dni, 'aktywny dzień', 'aktywne dni', 'aktywnych dni')} "
            f"— {opis_okresu}.")

    return karta_formularza(
        [siatka, legenda, ft.Text(opis, size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT)],
        f"Aktywność: {opis_okresu}", ft.Icons.CALENDAR_MONTH, domyslnie_otwarte=True, page=page
    )


__all__ = [
    "KOLORY_SERII_KOSZTU",
    "OKNA_CZASU",
    "POSTACIE_RDR",
    "PROG_DROZENIA",
    "MAKS_PUNKTOW_KRZYWEJ",
    "ROLA_STATUSU_INTERWALU",
    "ZAKRESY_CZASU",
    "_OPISY_ZAKRESU",
    "_SKALA_KONDYCJI",
    "_chip_maly",
    "_jednostka_rdr",
    "_kropka_legendy",
    "_pigulka_chipow",
    "_tekst_roznicy",
    "_kwota_osi",
    "_przesun_miesiac",
    "granica_zakresu",
    "klucze_miesiecy_zakresu",
    "krok_etykiet_osi",
    "okresy_slupkow",
    "opis_zakresu",
    "tygodnie_zakresu",
    "pasek_lat_rdr",
    "pasek_okna_kroczacego",
    "pasek_zakresu_czasu",
    "zakres_wykresu",
    "gauge_kondycji",
    "heatmapa_aktywnosci",
    "karta_analizy",
    "karta_kosztu_1000km",
    "karta_rok_do_roku",
    "karta_kosztu_skumulowanego",
    "kolor_kondycji_plynny",
    "krzywa_1000_w_jednostce",
    "liczniki_interwalu",
    "odznaka_zrodla_przebiegu",
    "pasek_budzetu",
    "pasek_postepu",
    "sparkline",
    "wskaznik_baku",
    "wykres_kosztu_1000km",
    "wykres_rok_do_roku",
    "wykres_kosztu_skumulowanego",
    "wykres_przebiegu",
    "znacznik_trendu",
]
