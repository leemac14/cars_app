"""Interfejs synchronizacji: stan, konflikty, przycisk i wskaźnik."""

import asyncio
import db
import flet as ft
import sync
from datetime import datetime, timedelta

from .stale import KOLOR_STATUS, RADIUS
from .dialogi import otworz_dialog, pokaz_komunikat, pokaz_ladowanie, przejdz, ukryj_ladowanie, zamknij_dialog


def _moment_ostatniej_synchronizacji():
    zapis = db.pobierz_ustawienie("ostatnia_synchronizacja")
    if not zapis:
        return None
    try:
        return datetime.strptime(zapis, "%d.%m.%Y %H:%M")
    except ValueError:
        return None


def tekst_ostatniej_synchronizacji(krotki=True):
    """Względny opis czasu ostatniej udanej synchronizacji (zapisywanej lokalnie
    przez sync.synchronizuj_wszystko).

    Domyślnie forma KRÓTKA — sam czas, bez słowa „Zsynchronizowano” (przycisk
    tuż nad etykietą i tak mówi, o co chodzi) i bez dopisku o kolejce offline.
    Ten dopisek potrafił urosnąć do „Zsynchronizowano 15.08.2026 14:32 • 3
    pojazdy czekają na wysłanie zmian” i rozpychał wiersz nagłówka, w którym
    obok stoją inne przyciski; zaległości pokazuje teraz kropka na przycisku
    (patrz przycisk_synchronizacji). Forma pełna została do tooltipów.
    """
    moment = _moment_ostatniej_synchronizacji()
    if not moment:
        return "Nigdy" if krotki else "Nigdy nie synchronizowano"

    sekundy = max(0, (datetime.now() - moment).total_seconds())
    dzis = datetime.now().date()

    if sekundy < 60:
        czas = "przed chwilą"
    elif sekundy < 3600:
        czas = f"{int(sekundy // 60)} min temu"
    elif moment.date() == dzis:
        czas = f"{int(sekundy // 3600)} godz. temu"
    elif moment.date() == (dzis - timedelta(days=1)):
        czas = f"wczoraj {moment.strftime('%H:%M')}"
    elif moment.year == dzis.year:
        czas = moment.strftime("%d.%m")
    else:
        czas = moment.strftime("%d.%m.%y")

    if krotki:
        return czas

    pelny = f"Zsynchronizowano {czas}"
    zalegle = db.opis_oczekujacej_synchronizacji()
    return f"{pelny} • {zalegle}" if zalegle else pelny


def wypchnij_w_tle(page: ft.Page, auto_id, powod="zapis"):
    """Zastępuje dawne `try: ... except Exception: pass` przy auto-synchronizacji
    po zapisie. Różnica: nieudana próba (brak sieci) nie znika — ląduje w kolejce
    kolejka_sync i zostanie ponowiona przy następnym zapisie albo starcie aplikacji.
    Dla pojazdu niewspółdzielonego nie robi nic."""
    if not auto_id:
        return
    try:
        wspolny_id, _ = sync.czy_udostepniony(auto_id)
    except Exception:
        return
    if not wspolny_id:
        return

    async def _zadanie():
        await asyncio.to_thread(sync.synchronizuj_w_tle, auto_id, powod)
        await asyncio.to_thread(sync.przetworz_kolejke_sync)

    page.run_task(_zadanie)


def podsumowanie_konfliktow(konflikty, maks_nazw=2):
    """Jednozdaniowe streszczenie konfliktów do snackbara — z nazwami pierwszych
    rekordów zamiast samej liczby."""
    if not konflikty:
        return ""
    nazwy = [k["opis"] for k in konflikty[:maks_nazw]]
    reszta = len(konflikty) - len(nazwy)
    tekst = ", ".join(nazwy)
    if reszta > 0:
        tekst += f" i {reszta} inn." if reszta > 1 else " i 1 inny"
    return f"Edycja z dwóch urządzeń — nadpisano: {tekst}. Zachowano wersję z tego telefonu."


def pokaz_dialog_konfliktow(page: ft.Page, konflikty):
    """Pełna lista nadpisanych rekordów z ostatniej synchronizacji."""
    if not konflikty:
        return
    wiersze = [
        ft.Row([
            ft.Icon(ft.Icons.MERGE_TYPE, size=16, color=ft.Colors.AMBER_700),
            ft.Text(k["opis"], size=13, expand=True),
        ], spacing=8)
        for k in konflikty
    ]
    dlg = ft.AlertDialog(
        title=ft.Row([
            ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=ft.Colors.AMBER_700),
            ft.Text("Edycja z dwóch urządzeń", weight="bold", expand=True),
        ], spacing=8),
        content=ft.Column(
            [ft.Text(
                "Te rekordy zmieniły się równolegle na innym urządzeniu. Zachowano wersję "
                "z tego telefonu — sprawdź, czy nie trzeba czegoś poprawić ręcznie.",
                size=12, color=ft.Colors.ON_SURFACE_VARIANT
            ), ft.Divider(height=10)] + wiersze,
            tight=True, spacing=6, scroll=ft.ScrollMode.AUTO
        ),
        actions=[ft.TextButton("Rozumiem", on_click=lambda e: zamknij_dialog(page, dlg))]
    )
    otworz_dialog(page, dlg)


def funkcja_szybkiej_synchronizacji(page: ft.Page, auto_id, trasa_powrotu):
    """Zwraca gotowy async callback do użycia z przycisk_synchronizacji() —
    synchronizuje dany pojazd i odświeża podaną trasę. Skraca boilerplate
    powtarzany w wielu widokach (pierwowzór: MainView._synchronizuj_teraz)."""
    async def _synchronizuj():
        try:
            wyslano, pobrano = await asyncio.to_thread(sync.synchronizuj_wszystko, auto_id)
            await asyncio.to_thread(sync.przetworz_kolejke_sync)
            przejdz(page, trasa_powrotu)
            konflikty = sync.pobierz_konflikty_ostatniej_synchronizacji()
            if konflikty:
                pokaz_komunikat(page, podsumowanie_konfliktow(konflikty), ft.Colors.AMBER_700)
                pokaz_dialog_konfliktow(page, konflikty)
            else:
                pokaz_komunikat(page, f"Wysłano {wyslano}, pobrano {pobrano} nowych rekordów.")
        except Exception as ex:
            db.zakolejkuj_synchronizacje(auto_id, "reczna", str(ex))
            pokaz_komunikat(
                page,
                f"Błąd synchronizacji: {ex}. Zmiany zostały zakolejkowane i spróbujemy ponownie automatycznie.",
                ft.Colors.RED_700
            )
    return _synchronizuj


def przycisk_synchronizacji(page: ft.Page, funkcja_sync, tekst="Synchronizuj", pokaz_czas=True):
    """Spójny, dobrze widoczny przycisk szybkiej synchronizacji z chmurą — do użycia
    w nagłówkach zakładek przy współdzielonych pojazdach. Zawsze pokazuje pełnoekranowy
    dialog ładowania na czas operacji (patrz pokaz_ladowanie), w przeciwieństwie do
    poprzednich, ledwo widocznych samych ikonek.
    funkcja_sync: async callback bez argumentów wykonujący faktyczną synchronizację
    (zwykle cienki wrapper na sync.synchronizuj_wszystko, patrz też
    funkcja_szybkiej_synchronizacji) — sam odpowiada za komunikaty o sukcesie/błędzie.
    pokaz_czas: dokleja pod przyciskiem małą etykietę 'Zsynchronizowano X temu'."""
    # Szerokość CAŁEGO bloku jest z góry ograniczona: przycisk z podpisem stoi
    # w tym samym wierszu co tytuł sekcji i inne akcje, więc rozciągliwy tekst
    # potrafił zepchnąć sąsiadów poza ekran.
    SZEROKOSC = 132

    def _opis_tooltipa():
        # Forma pełna sama dokleja informację o kolejce offline, jeśli coś w niej
        # jest — to tutaj, a nie pod przyciskiem, jest na nią miejsce.
        return f"Synchronizuj z partnerem\n{tekst_ostatniej_synchronizacji(krotki=False)}"

    etykieta_czasu = ft.Text(
        tekst_ostatniej_synchronizacji(), size=10, color=ft.Colors.ON_SURFACE_VARIANT,
        no_wrap=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
        text_align=ft.TextAlign.CENTER,
    )
    # Kropka zamiast zdania „3 pojazdy czekają na wysłanie zmian” — ta sama
    # informacja, zero wpływu na szerokość. Szczegóły siedzą w tooltipie.
    kropka_zalegle = ft.Container(
        width=7, height=7, border_radius=RADIUS["pill"], bgcolor=ft.Colors.ORANGE_700,
        visible=bool(db.opis_oczekujacej_synchronizacji()),
    )

    def _odswiez_opisy():
        etykieta_czasu.value = tekst_ostatniej_synchronizacji()
        kropka_zalegle.visible = bool(db.opis_oczekujacej_synchronizacji())
        przycisk.tooltip = _opis_tooltipa()

    def _klik(e):
        async def _zrob():
            dlg = pokaz_ladowanie(page, "Synchronizowanie danych...")
            try:
                await funkcja_sync()
            finally:
                ukryj_ladowanie(page, dlg)
                _odswiez_opisy()
                try:
                    page.update()
                except Exception:
                    pass
        page.run_task(_zrob)

    przycisk = ft.Container(
        height=36,
        padding=ft.Padding(12, 0, 12, 0),
        border_radius=RADIUS["pill"],
        bgcolor=ft.Colors.with_opacity(0.14, ft.Colors.PRIMARY),
        ink=True,
        alignment=ft.Alignment.CENTER,
        tooltip=_opis_tooltipa(),
        on_click=_klik,
        content=ft.Row([
            ft.Icon(ft.Icons.SYNC, size=16, color=ft.Colors.PRIMARY),
            ft.Text(tekst, size=12, weight="bold", color=ft.Colors.PRIMARY, no_wrap=True),
            kropka_zalegle,
        ], spacing=6, tight=True)
    )

    if not pokaz_czas:
        return przycisk

    return ft.Container(
        width=SZEROKOSC,
        content=ft.Column(
            [przycisk, etykieta_czasu],
            spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True
        ),
    )


def wskaznik_synchronizacji(page: ft.Page, auto_id, rozmiar=15):
    """Mała chmurka przy nazwie pojazdu, widoczna TYLKO wtedy, gdy ten pojazd ma
    w kolejce niewysłane zmiany. Wcześniej ten stan dało się zobaczyć dopiero po
    wejściu w ekran Współdzielenia — teraz jest widoczny od razu na starcie,
    a dotknięcie prowadzi prosto tam, gdzie można to naprawić."""
    try:
        oczekuje = db.czy_auto_oczekuje_synchronizacji(auto_id)
    except Exception:
        oczekuje = False
    if not oczekuje:
        # Zerowy kontener zamiast None — dzięki temu wywołujący może wstawić go
        # w Row bez sprawdzania i układ nie skacze przy przełączaniu pojazdów.
        return ft.Container(width=0, height=0)

    return ft.Container(
        padding=ft.Padding.only(left=4),
        tooltip="Są zmiany niewysłane do chmury — dotknij, aby zsynchronizować",
        on_click=lambda e: przejdz(page, "/wspoldzielenie"),
        content=ft.Icon(ft.Icons.CLOUD_UPLOAD_OUTLINED, size=rozmiar, color=KOLOR_STATUS["warning"]),
    )


__all__ = [
    "_moment_ostatniej_synchronizacji",
    "funkcja_szybkiej_synchronizacji",
    "podsumowanie_konfliktow",
    "pokaz_dialog_konfliktow",
    "przycisk_synchronizacji",
    "tekst_ostatniej_synchronizacji",
    "wskaznik_synchronizacji",
    "wypchnij_w_tle",
]
