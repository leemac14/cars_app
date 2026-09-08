"""Interfejs synchronizacji: stan, role, konflikty, przycisk i wskaźnik."""

import asyncio
import db
import flet as ft
import log
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


def podsumowanie_odrzuconych(odrzucone, maks_nazw=2):
    """Zmiany cofnięte, bo dotyczyły cudzych wpisów przy roli współautora."""
    if not odrzucone:
        return ""
    nazwy = [k["opis"] for k in odrzucone[:maks_nazw]]
    reszta = len(odrzucone) - len(nazwy)
    tekst = ", ".join(nazwy)
    if reszta > 0:
        tekst += f" i {reszta} inn." if reszta > 1 else " i 1 inny"
    return f"Nie możesz zmieniać cudzych wpisów — przywrócono wersję z chmury: {tekst}."


def pokaz_dialog_konfliktow(page: ft.Page, konflikty, auto_id=None, po_zmianie=None):
    """Pełna lista nadpisanych rekordów z ostatniej synchronizacji.

    Gdy podano `auto_id`, okno pozwala też cofnąć nadpisanie: wersje z chmury
    zostały zapamiętane w chwili wykrycia konfliktu (patrz
    sync._zarejestruj_konflikt), więc jest jeszcze co przywracać. Wcześniej
    jedynym wyjściem był przycisk „Rozumiem” i ręczne przepisywanie danych."""
    if not konflikty:
        return

    def wiersz(k):
        opisy = [ft.Text(k["opis"], size=13, expand=True)]
        if k.get("opis_zdalny") and k["opis_zdalny"] != k["opis"]:
            opisy.append(ft.Text(f"w chmurze było: {k['opis_zdalny']}", size=11,
                                 italic=True, color=ft.Colors.ON_SURFACE_VARIANT))
        return ft.Row([
            ft.Icon(ft.Icons.MERGE_TYPE, size=16, color=ft.Colors.AMBER_700),
            ft.Column(opisy, spacing=1, tight=True, expand=True),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START)

    wiersze = [wiersz(k) for k in konflikty]

    def _wez_z_chmury(e):
        zamknij_dialog(page, dlg)

        async def _zrob():
            okno = pokaz_ladowanie(page, "Przywracanie wersji z chmury...")
            try:
                ile = await asyncio.to_thread(sync.przyjmij_wersje_z_chmury, auto_id, konflikty)
                ukryj_ladowanie(page, okno)
                if po_zmianie:
                    po_zmianie()
                else:
                    przejdz(page, page.route or "/")
                pokaz_komunikat(page, f"Przywrócono wersję z chmury dla {ile} rekordów.")
            except Exception as ex:
                ukryj_ladowanie(page, okno)
                pokaz_komunikat(page, f"Nie udało się przywrócić: {ex}", ft.Colors.RED_700)

        page.run_task(_zrob)

    da_sie_cofnac = bool(auto_id) and any(k.get("dane_zdalne") is not None for k in konflikty)

    akcje = [ft.TextButton("Zostaw moją wersję", on_click=lambda e: zamknij_dialog(page, dlg))]
    if da_sie_cofnac:
        akcje.append(ft.FilledButton("Weź wersję z chmury", icon=ft.Icons.CLOUD_DOWNLOAD, on_click=_wez_z_chmury))

    dlg = ft.AlertDialog(
        title=ft.Row([
            ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=ft.Colors.AMBER_700),
            ft.Text("Edycja z dwóch urządzeń", weight="bold", expand=True),
        ], spacing=8),
        content=ft.Column(
            [ft.Text(
                "Te rekordy zmieniły się równolegle na innym urządzeniu. Zachowano wersję "
                "z tego telefonu — możesz to zostawić albo wrócić do wersji z chmury.",
                size=12, color=ft.Colors.ON_SURFACE_VARIANT
            ), ft.Divider(height=10)] + wiersze,
            tight=True, spacing=6, scroll=ft.ScrollMode.AUTO
        ),
        actions=akcje,
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
            odrzucone = sync.pobierz_odrzucone_ostatniej_synchronizacji()
            if konflikty:
                pokaz_komunikat(page, podsumowanie_konfliktow(konflikty), ft.Colors.AMBER_700)
                pokaz_dialog_konfliktow(page, konflikty, auto_id)
            elif odrzucone:
                pokaz_komunikat(page, podsumowanie_odrzuconych(odrzucone), ft.Colors.ORANGE_700)
            elif db.czy_tylko_podglad(auto_id):
                pokaz_komunikat(page, f"Pobrano {pobrano} zmian. Ten pojazd masz w trybie tylko do odczytu.")
            else:
                pokaz_komunikat(page, f"Wysłano {wyslano}, pobrano {pobrano} nowych rekordów.")
        except sync.SynchronizacjaWToku:
            pokaz_komunikat(page, "Synchronizacja już trwa — chwilę to potrwa.", ft.Colors.ON_SURFACE_VARIANT)
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
                    log.polkniety("odświeżenie ekranu po synchronizacji")
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


# ============================ ROLE WSPÓŁDZIELENIA ============================
IKONY_ROL = {
    db.ROLA_WLASCICIEL: ft.Icons.KEY,
    db.ROLA_PELNA: ft.Icons.EDIT,
    db.ROLA_WSPOLAUTOR: ft.Icons.EDIT_NOTE,
    db.ROLA_PODGLAD: ft.Icons.VISIBILITY,
}

KOLORY_ROL = {
    db.ROLA_WLASCICIEL: ft.Colors.PRIMARY,
    db.ROLA_PELNA: ft.Colors.PRIMARY,
    db.ROLA_WSPOLAUTOR: ft.Colors.TEAL_700,
    db.ROLA_PODGLAD: ft.Colors.BLUE_GREY,
}


def odznaka_roli(auto_id, rozmiar=11):
    """Mały znacznik roli do postawienia obok nazwy pojazdu. Dla właściciela
    i pełnego dostępu jest pusty — to stan domyślny i nie ma o czym informować."""
    try:
        rola = db.rola_pojazdu(auto_id)
    except Exception:
        return ft.Container(width=0, height=0)
    if rola in db.ROLE_Z_PELNYM_DOSTEPEM:
        return ft.Container(width=0, height=0)

    kolor = KOLORY_ROL.get(rola, ft.Colors.BLUE_GREY)
    return ft.Container(
        padding=ft.Padding(6, 2, 6, 2),
        border_radius=RADIUS["pill"],
        bgcolor=ft.Colors.with_opacity(0.14, kolor),
        tooltip=db.OPISY_ROL.get(rola, ""),
        content=ft.Row([
            ft.Icon(IKONY_ROL.get(rola, ft.Icons.VISIBILITY), size=rozmiar + 1, color=kolor),
            ft.Text(db.ETYKIETY_ROL.get(rola, rola), size=rozmiar, weight="bold", color=kolor, no_wrap=True),
        ], spacing=4, tight=True),
    )


def pasek_roli(page: ft.Page, auto_id):
    """Pasek nad treścią ekranu, gdy pojazd nie jest w pełni mój. Bez niego
    „dlaczego nie ma przycisku dodawania” byłoby zagadką — przyciski po prostu
    znikają, a użytkownik nie wie, że to celowe."""
    try:
        rola = db.rola_pojazdu(auto_id)
    except Exception:
        return ft.Container(width=0, height=0)
    if rola in db.ROLE_Z_PELNYM_DOSTEPEM:
        return ft.Container(width=0, height=0)

    kolor = KOLORY_ROL.get(rola, ft.Colors.BLUE_GREY)
    return ft.Container(
        padding=ft.Padding(12, 8, 12, 8),
        border_radius=RADIUS["sm"],
        bgcolor=ft.Colors.with_opacity(0.10, kolor),
        on_click=lambda e: przejdz(page, "/wspoldzielenie"),
        content=ft.Row([
            ft.Icon(IKONY_ROL.get(rola, ft.Icons.VISIBILITY), size=17, color=kolor),
            ft.Column([
                ft.Text(db.ETYKIETY_ROL.get(rola, rola), size=12, weight="bold", color=kolor),
                ft.Text(db.OPISY_ROL.get(rola, ""), size=11, color=ft.Colors.ON_SURFACE_VARIANT),
            ], spacing=0, tight=True, expand=True),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )


def wolno_dodawac(auto_id):
    try:
        return db.czy_moge_dodawac(auto_id)
    except Exception:
        return True


def wolno_zmieniac(auto_id, autor=None):
    try:
        return db.czy_moge_zmieniac_wpis(auto_id, autor)
    except Exception:
        return True


def zablokowane(page: ft.Page, auto_id, autor=None, pokaz=True):
    """Jedno pytanie zadawane przed każdą akcją zmieniającą dane: „czy to jest
    zabronione?”. Zwraca True i — domyślnie — tłumaczy dlaczego.

    Sam interfejs nie jest zabezpieczeniem; twardą granicę stawia wyzwalacz
    w Supabase, a druga warstwa siedzi w sync.py (przy roli podglądu nic nie
    jest wysyłane). To jest warstwa trzecia: żeby nie dało się kliknąć czegoś,
    co i tak zostanie cofnięte."""
    if wolno_zmieniac(auto_id, autor):
        return False
    if pokaz:
        rola = db.rola_pojazdu(auto_id)
        if rola == db.ROLA_PODGLAD:
            tekst = "Ten pojazd masz w trybie tylko do odczytu — możesz go oglądać, ale nie zmieniać."
        else:
            tekst = "To nie jest Twój wpis. Jako współautor zmieniasz tylko to, co sam dodałeś."
        pokaz_komunikat(page, tekst, ft.Colors.ORANGE_700)
    return True


# ========================= AUTOMATYCZNA SYNCHRONIZACJA =========================
# Ekrany, na których wolno przeładować widok po cichym pobraniu danych. Na
# formularzu przeładowanie skasowałoby to, co użytkownik właśnie wpisuje.
TRASY_BEZPIECZNE_DO_ODSWIEZENIA = ("/", "/wspoldzielenie", "/podzial", "/timeline")


async def synchronizuj_cicho(page: ft.Page, auto_id, odswiez=True):
    """Synchronizacja bez okna ładowania i bez komunikatu o sukcesie —
    do cyklicznego odpytywania w tle. Nie rzuca wyjątkami."""
    if not auto_id:
        return 0, 0
    try:
        wspolny_id, _ = await asyncio.to_thread(sync.czy_udostepniony, auto_id)
    except Exception:
        return 0, 0
    if not wspolny_id:
        return 0, 0

    try:
        wyslano, pobrano = await asyncio.to_thread(sync.synchronizuj_wszystko, auto_id, False, False)
    except sync.SynchronizacjaWToku:
        return 0, 0
    except Exception:
        return 0, 0  # brak sieci przy cichym odpytywaniu nie ma prawa nic pokazać

    if pobrano and odswiez:
        trasa = page.route or "/"
        if trasa in TRASY_BEZPIECZNE_DO_ODSWIEZENIA:
            try:
                przejdz(page, trasa)
            except Exception:
                log.polkniety(f"odświeżenie ekranu {trasa} po dociągnięciu zmian")
        try:
            pokaz_komunikat(page, f"Pobrano {pobrano} zmian od pozostałych użytkowników.")
        except Exception:
            log.polkniety("komunikat o pobranych zmianach")
    return wyslano, pobrano


def uruchom_auto_synchronizacje(page: ft.Page, state):
    """Cykliczne dociąganie zmian, dopóki aplikacja jest otwarta, plus jedno
    dociągnięcie przy powrocie z tła.

    Do tej pory synchronizacja ruszała wyłącznie po zapisie formularza albo
    z przycisku — kto tylko OGLĄDAŁ współdzielony pojazd (a przy roli „tylko
    podgląd” to jedyne, co robi) nie zobaczyłby cudzych zmian, dopóki sam
    czegoś nie kliknął."""
    if getattr(page, "_auto_sync_dziala", False):
        return
    page._auto_sync_dziala = True

    async def _petla():
        while True:
            try:
                minuty = await asyncio.to_thread(db.interwal_auto_synchronizacji)
            except Exception:
                minuty = 15
            await asyncio.sleep(max(60, int(minuty) * 60))
            try:
                if not await asyncio.to_thread(db.czy_auto_synchronizacja):
                    continue
                await synchronizuj_cicho(page, getattr(state, "auto_id", None))
            except Exception:
                # Pętla tła nie ma prawa się wywalić i zabrać ze sobą aplikacji.
                log.polkniety("cykl automatycznej synchronizacji")

    page.run_task(_petla)

    # Powrót z tła to najczęstszy moment, w którym dane są nieaktualne: telefon
    # leżał w kieszeni, ktoś w tym czasie zatankował.
    #
    # run_task sprawdza `asyncio.iscoroutinefunction(handler)`, więc MUSI dostać
    # prawdziwe `async def`. Lambda zwracająca korutynę jest odrzucana tak samo
    # jak zwykła funkcja („handler must be a coroutine function") — myli to, bo
    # `asyncio.create_task(lambda_zwracajaca_korutyne())` przechodzi bez problemu.
    async def _dociagnij_w_tle():
        await synchronizuj_cicho(page, getattr(state, "auto_id", None))

    def _zmiana_stanu(e):
        # Flet woła ten handler z wnętrza pętli zdarzeń przy minimalizacji
        # i przywracaniu okna. Wyjątek stąd nie ma gdzie wylądować poza konsolą,
        # więc całość idzie w jedno try: dociąganie danych nigdy nie może
        # zepsuć chowania aplikacji do paska.
        try:
            if not str(getattr(e, "state", "")).upper().endswith("RESUME"):
                return
            if not db.czy_auto_synchronizacja():
                return
            page.run_task(_dociagnij_w_tle)
        except Exception:
            log.polkniety("obsługa powrotu aplikacji z tła")

    try:
        page.on_app_lifecycle_state_change = _zmiana_stanu
    except Exception:
        # Starsze wersje Fleta nie mają tego zdarzenia — zostaje sama pętla.
        log.polkniety("podpięcie zdarzenia stanu aplikacji")


__all__ = [
    "IKONY_ROL",
    "KOLORY_ROL",
    "TRASY_BEZPIECZNE_DO_ODSWIEZENIA",
    "_moment_ostatniej_synchronizacji",
    "funkcja_szybkiej_synchronizacji",
    "odznaka_roli",
    "pasek_roli",
    "podsumowanie_konfliktow",
    "podsumowanie_odrzuconych",
    "pokaz_dialog_konfliktow",
    "przycisk_synchronizacji",
    "synchronizuj_cicho",
    "tekst_ostatniej_synchronizacji",
    "uruchom_auto_synchronizacje",
    "wolno_dodawac",
    "wolno_zmieniac",
    "wskaznik_synchronizacji",
    "wypchnij_w_tle",
    "zablokowane",
]
