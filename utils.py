import flet as ft
from datetime import datetime, date, timedelta, timezone
import re
import db
import os
import asyncio
import urllib.parse
import inspect
from state import MIESIACE_NAZWY
from date import parsuj_date
import sync

FILTR_CALKOWITY = None
FILTR_DZIESIETNY = None

MAPA_KOLOROW = {
    "Indygo": ft.Colors.INDIGO,
    "Czerwony": ft.Colors.RED,
    "Zielony": ft.Colors.GREEN,
    "Niebieski": ft.Colors.BLUE,
    "Szary": ft.Colors.GREY_500,
    "Pomarańczowy": ft.Colors.ORANGE,
    "Fioletowy": ft.Colors.PURPLE,
    "Różowy": ft.Colors.PINK_200,
    "Żółty": ft.Colors.YELLOW,
    "Limonkowy": ft.Colors.LIME,
}

def formatuj_liczba(wartosc, decimale=2):
    try:
        wartosc = float(wartosc)
    except (TypeError, ValueError):
        wartosc = 0.0
    if decimale > 0:
        tekst = f"{wartosc:,.{decimale}f}"
        czesc_calk, _, czesc_dziesiet = tekst.partition(".")
        return f"{czesc_calk.replace(',', ' ')},{czesc_dziesiet}"
    else:
        return f"{int(round(wartosc)):,}".replace(",", " ")

# ============== DESIGN TOKENS ==============
RADIUS = {"xs": 8, "sm": 10, "md": 12, "lg": 20, "xl": 28, "pill": 999}
SPACING = {"xs": 4, "sm": 8, "md": 16, "lg": 20, "xl": 32}
FS = {
    "caption": 11, "label": 12, "body": 13, "body_strong": 14,
    "title": 16, "heading": 18, "display": 22,
}
KOLOR_STATUS = {
    "critical": ft.Colors.RED_700,
    "warning": ft.Colors.ORANGE_700,
    "ok": ft.Colors.GREEN_700,
    "neutral": ft.Colors.ON_SURFACE_VARIANT,
}


def _czy_ciemny(page: ft.Page = None) -> bool:
    if page is None:
        return False
    try:
        if page.theme_mode == ft.ThemeMode.DARK:
            return True
        if page.theme_mode == ft.ThemeMode.LIGHT:
            return False
        return getattr(page, "platform_brightness", None) == ft.Brightness.DARK
    except Exception:
        return False

def tlo_karty(page: ft.Page = None, poziom=1):
    """Automatycznie dobiera przezroczystość koloru ON_SURFACE.
    W trybie ciemnym podwaja opacity dla zachowania kontrastu."""
    ciemny = _czy_ciemny(page)
    mnoznik = 2.0 if ciemny else 1.0

    if poziom == 1:   # Delikatne tło (karty w jasnym motywie — cień robi "unoszenie")
        return ft.Colors.with_opacity(0.03 * mnoznik, ft.Colors.ON_SURFACE)
    elif poziom == 2: # Średnie tło (pola formularza, karty w ciemnym motywie)
        return ft.Colors.with_opacity(0.08 * mnoznik, ft.Colors.ON_SURFACE)
    elif poziom == 3: # Najsilniejsze tło — dostępne do mocniejszych akcentów
        return ft.Colors.with_opacity(0.15 * mnoznik, ft.Colors.ON_SURFACE)
    return ft.Colors.TRANSPARENT

def cien_karty(page: ft.Page = None, poziom="md"):
    """Miękki, 'unoszący' cień w duchu Material 3 — WYŁĄCZNIE w trybie jasnym.
    W trybie ciemnym cień jest ledwo czytelny na ciemnym tle i tylko brudzi
    interfejs, dlatego zwracamy None — tam różnicujemy powierzchnie wyłącznie
    jaśniejszym `bgcolor` (patrz `powierzchnia_karty` niżej). Każdy poziom to
    dwie warstwy (blisko + rozlana), jak w prawdziwych cieniach Material 3."""
    if _czy_ciemny(page):
        return None
    warstwy = {
        "sm": [  # lekkie karty na listach — jeden, ciasny cień
            ft.BoxShadow(blur_radius=6, spread_radius=0, offset=ft.Offset(0, 1),
                         color=ft.Colors.with_opacity(0.05, ft.Colors.BLACK)),
        ],
        "md": [  # karty formularzy
            ft.BoxShadow(blur_radius=3, spread_radius=0, offset=ft.Offset(0, 1),
                         color=ft.Colors.with_opacity(0.04, ft.Colors.BLACK)),
            ft.BoxShadow(blur_radius=20, spread_radius=-6, offset=ft.Offset(0, 8),
                         color=ft.Colors.with_opacity(0.08, ft.Colors.BLACK)),
        ],
        "lg": [  # modale / bottom sheety
            ft.BoxShadow(blur_radius=4, spread_radius=0, offset=ft.Offset(0, 2),
                         color=ft.Colors.with_opacity(0.05, ft.Colors.BLACK)),
            ft.BoxShadow(blur_radius=28, spread_radius=-8, offset=ft.Offset(0, 14),
                         color=ft.Colors.with_opacity(0.12, ft.Colors.BLACK)),
        ],
    }
    return warstwy.get(poziom, warstwy["md"])


def powierzchnia_karty(page: ft.Page = None, cien="md"):
    """Gotowy zestaw {bgcolor, shadow} do rozpakowania (**) w Containerze
    karty/formularza. Jasny motyw: niemal przezroczyste tło + miękki cień
    (cień 'unosi' kartę). Ciemny motyw: cień wyłączony, więc tło podbijamy
    o jeden poziom mocniej (poziom=2), żeby granica karty była widoczna
    bez cienia — dokładnie tak, jak prosisz w pkt. 1."""
    if _czy_ciemny(page):
        return {"bgcolor": tlo_karty(page, poziom=2), "shadow": None}
    return {"bgcolor": tlo_karty(page, poziom=1), "shadow": cien_karty(page, cien)}

def parsuj_int(wartosc, domyslna=0):
    if wartosc is None: return domyslna
    tekst = str(wartosc).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not tekst: return domyslna
    try:
        return int(round(float(tekst)))
    except (ValueError, TypeError):
        dopasowanie = re.search(r"-?\d+", tekst)
        return int(dopasowanie.group()) if dopasowanie else domyslna

def parsuj_float(wartosc, domyslna=0.0):
    if wartosc is None: return domyslna
    tekst = str(wartosc).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not tekst: return domyslna
    try:
        return float(tekst)
    except (ValueError, TypeError):
        dopasowanie = re.search(r"-?\d+(\.\d+)?", tekst)
        return float(dopasowanie.group()) if dopasowanie else domyslna

def pokaz_komunikat(page: ft.Page, wiadomosc, kolor=ft.Colors.GREEN_700):
    snack = ft.SnackBar(ft.Text(str(wiadomosc)), bgcolor=kolor)
    if hasattr(page, "open"):
        page.open(snack)
    else:
        page.overlay.append(snack)
        snack.open = True
        page.update()

def pokaz_komunikat_cofnij(page: ft.Page, wiadomosc, wynik_usuwania, sekundy=5):
    """wynik_usuwania to słownik zwrócony przez db.usun_z_cofnieciem()."""
    if not wynik_usuwania:
        return pokaz_komunikat(page, wiadomosc, ft.Colors.RED_700)

    def po_cofnieciu(e):
        wynik_usuwania["cofnij"]()
        przejdz(page, page.route)

    snack = ft.SnackBar(
        content=ft.Text(str(wiadomosc)),
        action="Cofnij",
        on_action=po_cofnieciu,
        duration=sekundy * 1000,
    )
    if hasattr(page, "open"):
        page.open(snack)
    else:
        page.overlay.append(snack)
        snack.open = True
        page.update()

    async def _finalizuj_po_czasie():
        await asyncio.sleep(sekundy + 0.5)
        wynik_usuwania["finalizuj"]()

    page.run_task(_finalizuj_po_czasie)

def z_opoznieniem(page: ft.Page, funkcja, opoznienie=0.25):
    """Owija handler on_change pola wyszukiwania tak, by faktyczne wywołanie
    funkcja(e) nastąpiło dopiero po 'opoznienie' sekundach ciszy od ostatniego
    wciśnięcia klawisza — zapobiega przeliczaniu filtra (albo, w /szukaj,
    zapytania do bazy) przy KAŻDYM pojedynczym znaku, gdy lista ma setki wpisów.
    Użycie: on_change=utils.z_opoznieniem(self._page, moja_funkcja_filtrujaca)"""
    stan = {"licznik": 0}

    def on_change(e):
        stan["licznik"] += 1
        numer_wywolania = stan["licznik"]

        async def _po_ciszy():
            await asyncio.sleep(opoznienie)
            if stan["licznik"] == numer_wywolania:
                funkcja(e)

        page.run_task(_po_ciszy)

    return on_change

def otworz_dialog(page: ft.Page, kontrolka):
    if hasattr(page, "open"): page.open(kontrolka)
    elif hasattr(page, "show_dialog"): page.show_dialog(kontrolka)
    else:
        page.overlay.append(kontrolka)
        kontrolka.open = True
        page.update()

def zamknij_dialog(page: ft.Page, kontrolka):
    if hasattr(page, "close"): page.close(kontrolka)
    elif hasattr(page, "pop_dialog"): page.pop_dialog()
    else:
        kontrolka.open = False
        if kontrolka in page.overlay: page.overlay.remove(kontrolka)
        page.update()

def pokaz_ladowanie(page: ft.Page, tekst="Wczytywanie..."):
    """Blokujący, niezamykalny dialog ze spinnerem — używać w parze z
    ukryj_ladowanie() wokół operacji trwających dłużej niż mgnienie oka
    (np. synchronizacja z chmurą), żeby ekran nie wyglądał na zawieszony."""
    dlg = ft.AlertDialog(
        modal=True,
        content_padding=ft.Padding(25, 20, 25, 20),
        content=ft.Row([
            ft.ProgressRing(width=20, height=20, stroke_width=3, color=ft.Colors.PRIMARY),
            ft.Text(tekst, size=14),
        ], spacing=15, tight=True),
    )
    otworz_dialog(page, dlg)
    return dlg

def ukryj_ladowanie(page: ft.Page, dlg):
    if dlg is not None:
        zamknij_dialog(page, dlg)

def tekst_ostatniej_synchronizacji():
    """Zwraca czytelny, względny opis czasu ostatniej udanej synchronizacji
    (np. '4 min temu'), zapisywanej lokalnie przez sync.synchronizuj_wszystko.
    Nigdy nie synchronizowano -> 'Nigdy nie synchronizowano'."""
    zapis = db.pobierz_ustawienie("ostatnia_synchronizacja")
    if not zapis:
        return "Nigdy nie synchronizowano"
    try:
        moment = datetime.strptime(zapis, "%d.%m.%Y %H:%M")
    except ValueError:
        return "Nigdy nie synchronizowano"

    roznica = datetime.now() - moment
    sekundy = max(0, roznica.total_seconds())

    if sekundy < 60:
        return "Zsynchronizowano przed chwilą"
    if sekundy < 3600:
        return f"Zsynchronizowano {int(sekundy // 60)} min temu"
    if moment.date() == datetime.now().date():
        return f"Zsynchronizowano {int(sekundy // 3600)} godz. temu"
    if moment.date() == (datetime.now().date() - timedelta(days=1)):
        return f"Zsynchronizowano wczoraj o {moment.strftime('%H:%M')}"
    return f"Zsynchronizowano {moment.strftime('%d.%m.%Y %H:%M')}"

def funkcja_szybkiej_synchronizacji(page: ft.Page, auto_id, trasa_powrotu):
    """Zwraca gotowy async callback do użycia z przycisk_synchronizacji() —
    synchronizuje dany pojazd i odświeża podaną trasę. Skraca boilerplate
    powtarzany w wielu widokach (pierwowzór: MainView._synchronizuj_teraz)."""
    async def _synchronizuj():
        try:
            wyslano, pobrano = await asyncio.to_thread(sync.synchronizuj_wszystko, auto_id)
            przejdz(page, trasa_powrotu)
            konflikty = sync.pobierz_konflikty_ostatniej_synchronizacji()
            if konflikty:
                pokaz_komunikat(
                    page,
                    f"Wykryto edycję z dwóch urządzeń w {konflikty} rekordach — zachowano wersję z tego urządzenia.",
                    ft.Colors.AMBER_700
                )
            else:
                pokaz_komunikat(page, f"Wysłano {wyslano}, pobrano {pobrano} nowych rekordów.")
        except Exception as ex:
            pokaz_komunikat(page, f"Błąd synchronizacji: {ex}", ft.Colors.RED_700)
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
    etykieta_czasu = ft.Text(tekst_ostatniej_synchronizacji(), size=10, color=ft.Colors.ON_SURFACE_VARIANT)

    def _klik(e):
        async def _zrob():
            dlg = pokaz_ladowanie(page, "Synchronizowanie danych...")
            try:
                await funkcja_sync()
            finally:
                ukryj_ladowanie(page, dlg)
                etykieta_czasu.value = tekst_ostatniej_synchronizacji()
                try:
                    page.update()
                except Exception:
                    pass
        page.run_task(_zrob)

    przycisk = ft.Container(
        height=36,
        padding=ft.Padding(14, 0, 14, 0),
        border_radius=RADIUS["pill"],
        bgcolor=ft.Colors.with_opacity(0.14, ft.Colors.PRIMARY),
        ink=True,
        alignment=ft.Alignment.CENTER,
        tooltip="Synchronizuj z partnerem",
        on_click=_klik,
        content=ft.Row([
            ft.Icon(ft.Icons.SYNC, size=16, color=ft.Colors.PRIMARY),
            ft.Text(tekst, size=12, weight="bold", color=ft.Colors.PRIMARY),
        ], spacing=6, tight=True)
    )

    if not pokaz_czas:
        return przycisk

    return ft.Column([przycisk, etykieta_czasu], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True)

def otworz_dno(page: ft.Page, bottom_sheet):
    """Automatycznie zabezpiecza dolne menu przed zasłonięciem przez przyciski systemowe telefonu."""
    if hasattr(bottom_sheet, "content") and bottom_sheet.content:
        kontener = bottom_sheet.content
        if isinstance(kontener, ft.Container):
            # Jeśli w kontenerze jest kolumna elementów, włączamy scroll i doklejamy margines
            if isinstance(kontener.content, ft.Column):
                kontener.content.scroll = ft.ScrollMode.AUTO
                if not any(isinstance(c, ft.SafeArea) for c in kontener.content.controls):
                    kontener.content.controls.append(dol_bezpieczny(20))
            elif not isinstance(kontener.content, ft.SafeArea):
                kontener.content = ft.SafeArea(
                    content=kontener.content,
                    avoid_intrusions_top=False
                )
        elif not isinstance(bottom_sheet.content, ft.SafeArea):
            bottom_sheet.content = ft.SafeArea(
                content=bottom_sheet.content,
                avoid_intrusions_top=False
            )
            
    otworz_dialog(page, bottom_sheet)

def zamknij_dno(page: ft.Page, bottom_sheet):
    zamknij_dialog(page, bottom_sheet)

def pokaz_menu_kontekstowe(page: ft.Page, tytul: str, pozycje: list):
    """
    Tworzy i wyświetla ujednolicone menu kontekstowe (BottomSheet).
    Automatycznie zamyka menu przed wykonaniem podpiętej akcji (wspiera sync i async).
    """
    bs = ft.BottomSheet(ft.Container(padding=20, bgcolor=ft.Colors.SURFACE))

    def opakuj_akcje(akcja_docelowa):
        async def wrapper(e):
            zamknij_dno(page, bs)
            if akcja_docelowa:
                res = akcja_docelowa()
                # Używamy asyncio zamiast inspect
                import asyncio
                if asyncio.iscoroutine(res):
                    await res
        return wrapper

    elementy_menu = [
        ft.Text(tytul, weight="bold", size=18, color=ft.Colors.PRIMARY),
        ft.Divider()
    ]

    for poz in pozycje:
        ikona = poz.get("ikona")
        tekst = poz.get("tekst")
        akcja = poz.get("akcja")
        kolor = poz.get("kolor")
        
        elementy_menu.append(
            ft.ListTile(
                leading=ft.Icon(ikona, color=kolor) if ikona else None,
                title=ft.Text(tekst, color=kolor),
                on_click=opakuj_akcje(akcja)
            )
        )

    bs.content.content = ft.Column(elementy_menu, tight=True)
    otworz_dno(page, bs)

def potwierdz(page: ft.Page, tytul, tresc, po_potwierdzeniu, tekst_potwierdzenia="Usuń"):
    dlg = ft.AlertDialog(
        modal=True, title=ft.Text(tytul, weight="bold"), content=ft.Text(tresc),
        shape=ft.RoundedRectangleBorder(radius=RADIUS["lg"]),
    )
    def anuluj(e):
        zamknij_dialog(page, dlg)
    def zatwierdz(e):
        zamknij_dialog(page, dlg)
        po_potwierdzeniu()
    
    dlg.actions = [
        ft.TextButton("Anuluj", on_click=anuluj),
        ft.TextButton(tekst_potwierdzenia, style=ft.ButtonStyle(color=ft.Colors.RED_700), on_click=zatwierdz),
    ]
    dlg.actions_alignment = ft.MainAxisAlignment.END
    otworz_dialog(page, dlg)

def przejdz(page: ft.Page, trasa: str):
    page.route = trasa
    page.on_route_change(None)

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

                pole.error_text = None
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
        kontrolka.error_text = komunikat
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
        pole_przebiegu.error_text = "Niski przebieg — kliknij Zapisz ponownie, aby potwierdzić"
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
        pole_kwoty.error_text = "Możliwy duplikat — kliknij Zapisz ponownie, aby potwierdzić"
        page.update()
        pokaz_komunikat(page, ostrzezenie, ft.Colors.ORANGE_700)
        return True

    pole_kwoty._duplikat_potwierdzony = None
    return False

def przycisk_sortowania(page: ft.Page, state, klucz_stanu, opcje):
    pole_akt, malejaco_akt = state.sort.setdefault(klucz_stanu, (opcje[0][1], False))
    
    def zmien_pole(pole):
        _, mal = state.sort[klucz_stanu]
        state.sort[klucz_stanu] = (pole, mal)
        przejdz(page, page.route)
        
    def zmien_kierunek(e):
        pole, mal = state.sort[klucz_stanu]
        state.sort[klucz_stanu] = (pole, not mal)
        przejdz(page, page.route)

    etykieta_akt = next((et for et, p, _ in opcje if p == pole_akt), str(pole_akt))

    elementy_menu = []
    for etykieta, pole, _ in opcje:
        zaznaczone = (pole == pole_akt)
        elementy_menu.append(
            ft.PopupMenuItem(
                content=ft.Row([
                    ft.Icon(ft.Icons.CHECK, size=16, color=ft.Colors.PRIMARY, visible=zaznaczone),
                    ft.Text(etykieta, weight="bold" if zaznaczone else "normal")
                ]),
                on_click=lambda e, p=pole: zmien_pole(p)
            )
        )

    popup = ft.PopupMenuButton(
        items=elementy_menu,
        content=ft.Row([
            ft.Icon(ft.Icons.SORT_ROUNDED, size=14, color=ft.Colors.PRIMARY),  # Mniejsza ikona
            ft.Text(etykieta_akt, size=11, weight="bold", color=ft.Colors.PRIMARY),  # Mniejszy tekst
        ], spacing=2),
        tooltip="Wybierz pole sortowania"
    )

    return ft.Container(
        height=36,  # <-- SZTYWNA WYSOKOŚĆ
        bgcolor=ft.Colors.with_opacity(0.1, ft.Colors.PRIMARY),
        border_radius=18,
        padding=ft.Padding(12, 0, 12, 0),
        alignment=ft.Alignment.CENTER,
        content=ft.Row([
            popup,
            ft.Container(width=1, height=16, bgcolor=ft.Colors.with_opacity(0.2, ft.Colors.PRIMARY)),
            ft.IconButton(
                icon=ft.Icons.ARROW_DOWNWARD_ROUNDED if malejaco_akt else ft.Icons.ARROW_UPWARD_ROUNDED,
                icon_size=16,
                icon_color=ft.Colors.PRIMARY,
                tooltip="Zmień kierunek sortowania",
                on_click=zmien_kierunek,
                width=24,
                height=24,
                style=ft.ButtonStyle(padding=0)
            )
        ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    )

def posortuj_liste(lista, state, klucz_stanu, opcje):
    pole_akt, malejaco = state.sort.get(klucz_stanu, (opcje[0][1], False))
    for _, pole, fn in opcje:
        if pole == pole_akt:
            lista.sort(key=fn, reverse=malejaco)
            break
    return lista

def usun_auto(page: ft.Page, state):
    if not state.auto_id: return
    nazwa = state.auto_nazwa
    auto_id = state.auto_id

    def wykonaj():
        # Użycie nowej funkcji archiwizującej
        wynik = db.usun_auto_z_cofnieciem(auto_id)
        
        if wynik:
            oryg_cofnij = wynik["cofnij"]
            def nowe_cofnij():
                oryg_cofnij()
                # Po ewentualnym cofnięciu przywracamy aktywny pojazd w interfejsie
                state.auto_id = auto_id
                state.auto_nazwa = nazwa
                przejdz(page, "/")
            wynik["cofnij"] = nowe_cofnij

        state.auto_id = None
        db.zainicjuj_domyslne_auto(state)
        przejdz(page, "/")
        pokaz_komunikat_cofnij(page, f"Usunięto pojazd „{nazwa}” wraz z historią.", wynik)
        
    potwierdz(page, "Usunąć pojazd?", f"Czy na pewno chcesz usunąć „{nazwa}”? Zostanie usunięta cała historia serwisowa oraz fizyczne pliki zdjęć.", wykonaj)

def _sygnatura_powiadomien(powiadomienia):
    return frozenset((p["typ"], p["tytul"], p["status"]) for p in powiadomienia)

def przycisk_dzwonka(page: ft.Page, state) -> ft.Control:
    powiadomienia = db.pobierz_powiadomienia(state.auto_id)
    liczba = len(powiadomienia)
    sygnatura = _sygnatura_powiadomien(powiadomienia)
    widziana = state.powiadomienia_widziane.get(state.auto_id)
    juz_widziane = liczba > 0 and sygnatura == widziana
    ma_przeterminowane = any(p["status"] == "przeterminowane" for p in powiadomienia)

    if liczba == 0 or juz_widziane:
        kolor_ikony = ft.Colors.ON_SURFACE
    elif ma_przeterminowane:
        kolor_ikony = ft.Colors.RED_700
    else:
        kolor_ikony = ft.Colors.ORANGE_700

    ikona = ft.IconButton(
        icon=ft.Icons.NOTIFICATIONS_ROUNDED if liczba else ft.Icons.NOTIFICATIONS_OUTLINED,
        icon_color=kolor_ikony,
        icon_size=20,
        tooltip=f"{liczba} powiadomień" if liczba else "Brak powiadomień",
        width=36, height=36,
        style=ft.ButtonStyle(padding=0),
    )

    if liczba == 0:
        ikona.on_click = lambda e: pokaz_panel_powiadomien(page, state)
        return ikona

    odznaka = ft.Container(
        content=ft.Text(str(liczba) if liczba < 10 else "9+", size=9, color=ft.Colors.WHITE, weight="bold"),
        width=14, height=14, border_radius=7, bgcolor=ft.Colors.RED_700,
        alignment=ft.Alignment.CENTER,
    )
    odznaka_pozycja = ft.Container(odznaka, right=0, top=0, visible=not juz_widziane)

    def po_kliknieciu(e):
        state.powiadomienia_widziane[state.auto_id] = sygnatura
        ikona.icon_color = ft.Colors.ON_SURFACE
        odznaka_pozycja.visible = False
        page.update()
        pokaz_panel_powiadomien(page, state)

    ikona.on_click = po_kliknieciu

    return ft.Stack([ikona, odznaka_pozycja], width=36, height=36)

def pokaz_panel_powiadomien(page: ft.Page, state):
    bs = ft.BottomSheet(ft.Container())

    def idz_do(trasa):
        def handler(e):
            zamknij_dno(page, bs)
            przejdz(page, trasa)
        return handler

    def zaplac_cykliczny(wydatek_id):
        def handler(e):
            db.oznacz_zaplacony_wydatek_cykliczny(wydatek_id, state.auto_id)
            pokaz_komunikat(page, "Zapisano płatność i przesunięto termin.")
            przejdz(page, page.route)  # odświeża dzwonek/badge w tle; panel zostaje otwarty
            odswiez()
        return handler

    def odswiez():
        powiadomienia = db.pobierz_powiadomienia(state.auto_id)
        pozycje = [
            ft.Row([
                ft.Icon(ft.Icons.NOTIFICATIONS_ROUNDED, color=ft.Colors.PRIMARY),
                ft.Text("Powiadomienia", weight="bold", size=18, color=ft.Colors.PRIMARY)
            ], spacing=8),
            ft.Divider(height=1),
        ]

        if not powiadomienia:
            pozycje.append(ft.Container(
                padding=ft.Padding.symmetric(vertical=20),
                content=ft.Text("Brak zbliżających się terminów 🎉", italic=True, color=ft.Colors.ON_SURFACE_VARIANT)
            ))
        else:
            for p in powiadomienia:
                kolor = ft.Colors.RED_700 if p["status"] == "przeterminowane" else ft.Colors.ORANGE_700
                ikona = ft.Icons.WARNING if p["status"] == "przeterminowane" else ft.Icons.HOURGLASS_BOTTOM
                if p["typ"] == "cykliczny":
                    pozycje.append(ft.ListTile(
                        leading=ft.Icon(ikona, color=kolor),
                        title=ft.Text(p["tytul"], weight="bold"),
                        subtitle=ft.Text(p["opis"], color=kolor, size=13),
                        trailing=ft.TextButton("Zapłacone", on_click=zaplac_cykliczny(p["wydatek_id"])),
                    ))
                else:
                    pozycje.append(ft.ListTile(
                        leading=ft.Icon(ikona, color=kolor),
                        title=ft.Text(p["tytul"], weight="bold"),
                        subtitle=ft.Text(p["opis"], color=kolor, size=13),
                        on_click=idz_do(p["trasa"]),
                    ))

        bs.content = ft.Container(
            padding=20,
            bgcolor=ft.Colors.SURFACE,
            content=ft.Column(pozycje, tight=True, spacing=4, scroll=ft.ScrollMode.AUTO)
        )
        try:
            page.update()
        except Exception:
            pass

    odswiez()
    otworz_dno(page, bs)

def pokaz_panel_wydatkow_cyklicznych(page: ft.Page, state):
    """Lekki panel (BottomSheet) do zarządzania wydatkami cyklicznymi pojazdu
    (raty, abonamenty, ubezpieczenia ratalne) — bez osobnej trasy, analogicznie
    do pokaz_panel_powiadomien()."""
    bs = ft.BottomSheet(ft.Container())

    def odswiez():
        wpisy = db.pobierz_wydatki_cykliczne(state.auto_id)
        pozycje = [
            ft.Row([
                ft.Icon(ft.Icons.AUTORENEW, color=ft.Colors.PRIMARY),
                ft.Text("Wydatki cykliczne", weight="bold", size=18, color=ft.Colors.PRIMARY)
            ], spacing=8),
            ft.Divider(height=1),
        ]

        if not wpisy:
            pozycje.append(ft.Container(
                padding=ft.Padding.symmetric(vertical=15),
                content=ft.Text("Brak zapisanych wydatków cyklicznych.", italic=True, color=ft.Colors.ON_SURFACE_VARIANT)
            ))
        else:
            for w_id, nazwa, kwota, okres_dni, nastepna_data in wpisy:
                kolor, tekst_daty = kolor_i_tekst_terminu(nastepna_data)
                pozycje.append(ft.ListTile(
                    leading=ft.Icon(ft.Icons.AUTORENEW, color=kolor),
                    title=ft.Text(str(nazwa), weight="bold"),
                    subtitle=ft.Text(
                        f"{formatuj_liczba(kwota)} {symbol_waluty()} • co {okres_dni} dni • {tekst_daty or nastepna_data}",
                        size=12, color=kolor
                    ),
                    trailing=ft.PopupMenuButton(items=[
                        ft.PopupMenuItem(
                            content=ft.Row([ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN, size=18), ft.Text("Zapłacone")]),
                            on_click=lambda e, wid=w_id: zaplac(wid)
                        ),
                        ft.PopupMenuItem(
                            content=ft.Row([ft.Icon(ft.Icons.EDIT, size=18), ft.Text("Edytuj")]),
                            on_click=lambda e, w=(w_id, nazwa, kwota, okres_dni, nastepna_data): formularz(w)
                        ),
                        ft.PopupMenuItem(
                            content=ft.Row([ft.Icon(ft.Icons.DELETE, color=ft.Colors.RED, size=18), ft.Text("Usuń")]),
                            on_click=lambda e, wid=w_id: usun(wid)
                        ),
                    ])
                ))

        pozycje.append(ft.Divider(height=1))
        pozycje.append(ft.TextButton("➕ Dodaj wydatek cykliczny", on_click=lambda e: formularz(None)))

        bs.content = ft.Container(
            padding=20, bgcolor=ft.Colors.SURFACE,
            content=ft.Column(pozycje, tight=True, spacing=4, scroll=ft.ScrollMode.AUTO)
        )
        try:
            page.update()
        except Exception:
            pass

    def zaplac(wydatek_id):
        db.oznacz_zaplacony_wydatek_cykliczny(wydatek_id, state.auto_id)
        pokaz_komunikat(page, "Zapisano płatność i przesunięto termin.")
        odswiez()

    def usun(wydatek_id):
        def wykonaj():
            db.usun_wydatek_cykliczny(wydatek_id)
            odswiez()
            pokaz_komunikat(page, "Usunięto wydatek cykliczny.")
        potwierdz(page, "Usunąć?", "Czy na pewno usunąć ten wydatek cykliczny?", wykonaj)

    def formularz(istniejacy):
        edycja = istniejacy is not None
        w_id, nazwa_val, kwota_val, okres_val, data_val = istniejacy or (None, "", "", 30, datetime.now().strftime("%d.%m.%Y"))

        e_nazwa = ft.TextField(label="Nazwa (np. Rata leasingu, OC ratalne)", value=str(nazwa_val), **styl_pola())
        e_kwota = ft.TextField(label=f"Kwota ({symbol_waluty()})", value=str(kwota_val) if kwota_val else "", keyboard_type=ft.KeyboardType.NUMBER, **styl_pola())
        e_okres = ft.Dropdown(
            label="Powtarzaj co",
            options=[
                ft.DropdownOption(key="30", text="Miesiąc (30 dni)"),
                ft.DropdownOption(key="90", text="Kwartał (90 dni)"),
                ft.DropdownOption(key="180", text="Pół roku (180 dni)"),
                ft.DropdownOption(key="365", text="Rok (365 dni)"),
            ],
            value=str(okres_val) if str(okres_val) in ("30", "90", "180", "365") else "30",
            **styl_dropdown()
        )
        e_data = pole_daty(page, "Następna płatność", str(data_val))

        def zapisz(e):
            e_nazwa.error_text = None
            e_kwota.error_text = None
            n = (e_nazwa.value or "").strip()
            kw = parsuj_float(e_kwota.value, None)
            bledy = []
            if not n: bledy.append((e_nazwa, "Podaj nazwę"))
            if kw is None or kw <= 0: bledy.append((e_kwota, "Podaj poprawną kwotę"))
            if bledy:
                for kontrolka, komunikat in bledy: kontrolka.error_text = komunikat
                page.update()
                return
            okres_dni = parsuj_int(e_okres.value, 30)
            if edycja:
                db.edytuj_wydatek_cykliczny(w_id, n, kw, okres_dni, e_data.value)
            else:
                db.dodaj_wydatek_cykliczny(state.auto_id, n, kw, okres_dni, e_data.value)
            zamknij_dialog(page, dlg)
            odswiez()

        dlg = ft.AlertDialog(
            title=ft.Text("Edytuj wydatek" if edycja else "Nowy wydatek cykliczny", weight="bold"),
            content=ft.Column([e_nazwa, e_kwota, e_okres, e_data], tight=True, spacing=10),
            actions=[
                ft.TextButton("Anuluj", on_click=lambda e: zamknij_dialog(page, dlg)),
                ft.ElevatedButton("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY)
            ]
        )
        otworz_dialog(page, dlg)

    odswiez()
    otworz_dno(page, bs)

def zbuduj_pasek_glowny(page: ft.Page, state, cb_export, cb_import, cb_theme):
    pozycje = []
    
    pozycje.append(ft.PopupMenuItem(content=ft.Row([ft.Icon(ft.Icons.ADD, color=ft.Colors.GREEN, size=20), ft.Text("Dodaj nowy pojazd")]), on_click=lambda e: przejdz(page, "/auto/nowy")))
    if state.auto_id:
        pozycje.append(ft.PopupMenuItem(content=ft.Row([ft.Icon(ft.Icons.DELETE, color=ft.Colors.RED, size=20), ft.Text("Usuń pojazd")]), on_click=lambda e: usun_auto(page, state)))
    pozycje.append(ft.PopupMenuItem(content=ft.Row([ft.Icon(ft.Icons.COMPARE_ARROWS, color=ft.Colors.TEAL, size=20), ft.Text("Porównaj pojazdy")]), on_click=lambda e: przejdz(page, "/porownanie")))
    pozycje.append(ft.PopupMenuItem(content=ft.Row([ft.Icon(ft.Icons.PEOPLE, color=ft.Colors.TEAL, size=20), ft.Text("Współdziel pojazd")]), on_click=lambda e: przejdz(page, "/wspoldzielenie")))
    pozycje.append(ft.PopupMenuItem(content=ft.Row([ft.Icon(ft.Icons.CALCULATE, color=ft.Colors.TEAL, size=20), ft.Text("Podział kosztów")]), on_click=lambda e: przejdz(page, "/podzial")))
    
    pozycje.append(ft.PopupMenuItem(content=ft.Row([ft.Icon(ft.Icons.MAP, color=ft.Colors.PURPLE, size=20), ft.Text("Kalkulator podróży")]), on_click=lambda e: przejdz(page, "/kalkulator")))
    pozycje.append(ft.PopupMenuItem(content=ft.Row([ft.Icon(ft.Icons.TIMELINE, color=ft.Colors.INDIGO, size=20), ft.Text("Dziennik życia auta")]), on_click=lambda e: przejdz(page, "/timeline")))
    pozycje.append(ft.PopupMenuItem(content=ft.Row([ft.Icon(ft.Icons.AUTORENEW, color=ft.Colors.INDIGO, size=20), ft.Text("Wydatki cykliczne")]), on_click=lambda e: pokaz_panel_wydatkow_cyklicznych(page, state)))

    pozycje.append(ft.PopupMenuItem(content=ft.Divider(height=1)))
    pozycje.append(ft.PopupMenuItem(content=ft.Row([ft.Icon(ft.Icons.UPLOAD_FILE, color=ft.Colors.BLUE, size=20), ft.Text("Eksportuj bazę")]), on_click=cb_export))
    pozycje.append(ft.PopupMenuItem(content=ft.Row([ft.Icon(ft.Icons.SUMMARIZE, color=ft.Colors.TEAL, size=20), ft.Text("Eksport danych (CSV/PDF)")]), on_click=lambda e: przejdz(page, "/eksport")))
    pozycje.append(ft.PopupMenuItem(content=ft.Row([ft.Icon(ft.Icons.DOWNLOAD, color=ft.Colors.ORANGE, size=20), ft.Text("Importuj bazę")]), on_click=cb_import))

    pozycje.append(ft.PopupMenuItem(content=ft.Divider(height=1)))
    pozycje.append(ft.PopupMenuItem(content=ft.Row([ft.Icon(ft.Icons.SETTINGS, color=ft.Colors.GREY, size=20), ft.Text("Ustawienia")]), on_click=lambda e: przejdz(page, "/ustawienia")))
    
    IKONY_TRYBU_MOTYWU = {"jasny": ft.Icons.LIGHT_MODE, "ciemny": ft.Icons.DARK_MODE, "system": ft.Icons.BRIGHTNESS_AUTO}
    ETYKIETY_TRYBU_MOTYWU = {"jasny": "Tryb jasny", "ciemny": "Tryb ciemny", "system": "Tryb systemowy"}
    obecny_tryb = db.pobierz_tryb_motywu()
    nastepny_tryb = db.KOLEJNOSC_TRYBOW_MOTYWU[(db.KOLEJNOSC_TRYBOW_MOTYWU.index(obecny_tryb) + 1) % 3]
    pozycje.append(ft.PopupMenuItem(content=ft.Divider(height=1)))
    pozycje.append(ft.PopupMenuItem(content=ft.Row([ft.Icon(IKONY_TRYBU_MOTYWU[nastepny_tryb], color=ft.Colors.YELLOW, size=20), ft.Text(ETYKIETY_TRYBU_MOTYWU[nastepny_tryb])]), on_click=cb_theme))

    nowoczesny_naglowek = ft.Row([
        ft.Container(
            content=ft.Icon(ft.Icons.DIRECTIONS_CAR, size=18, color=ft.Colors.PRIMARY),
            bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.PRIMARY),
            border_radius=8,
            padding=5
        ),
        ft.Column([
            ft.Text("Menedżer Samochodowy", size=9, weight="bold", color=ft.Colors.PRIMARY, no_wrap=True),
            ft.Text("APLIKACJA KAMILA", weight="bold", size=14, no_wrap=True)
        ], spacing=0)
    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    return ft.AppBar(
        title=nowoczesny_naglowek,
        center_title=False, 
        bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.PRIMARY),
        actions=[
            ft.IconButton(
                icon=ft.Icons.SEARCH,
                icon_size=20,
                tooltip="Szukaj we wszystkim",
                on_click=lambda e: przejdz(page, "/szukaj"),
                width=36, height=36,
                style=ft.ButtonStyle(padding=0),
            ),
            przycisk_dzwonka(page, state),
            ft.PopupMenuButton(
                content=ft.Container(
                    width=36, height=36, alignment=ft.Alignment.CENTER,
                    content=ft.Icon(ft.Icons.MORE_VERT, size=20, color=ft.Colors.ON_SURFACE_VARIANT),
                ),
                tooltip="Menu główne",
                items=pozycje
            ),
        ]
    )

def zbuduj_pasek_z_powrotem(page: ft.Page, tytul, trasa_powrotu, on_save=None, akcje_dodatkowe=None, czy_zmieniono=None):
    def wroc(e):
        if czy_zmieniono and czy_zmieniono():
            def wykonaj(e2):
                zamknij_dialog(page, dlg)
                przejdz(page, trasa_powrotu)
            dlg = ft.AlertDialog(
                title=ft.Text("Niezapisane zmiany"),
                content=ft.Text("Masz niezapisane zmiany w formularzu. Wyjść bez zapisywania?"),
                actions=[
                    ft.TextButton("Anuluj", on_click=lambda e2: zamknij_dialog(page, dlg)),
                    ft.TextButton("Wyjdź bez zapisywania", on_click=wykonaj, style=ft.ButtonStyle(color=ft.Colors.RED)),
                ]
            )
            otworz_dialog(page, dlg)
        else:
            przejdz(page, trasa_powrotu)

    actions = []
    if on_save:
        actions.append(
            ft.IconButton(
                icon=ft.Icons.SAVE,
                icon_color=ft.Colors.PRIMARY,
                tooltip="Zapisz formularz",
                on_click=on_save
            )
        )
        actions.append(
            ft.PopupMenuButton(
                items=[
                    ft.PopupMenuItem(
                        content=ft.Row([
                            ft.Icon(ft.Icons.SAVE, color=ft.Colors.PRIMARY, size=20), 
                            ft.Text("Zapisz")
                        ]), 
                        on_click=on_save
                    ),
                    ft.PopupMenuItem(
                        content=ft.Row([
                            ft.Icon(ft.Icons.CANCEL, color=ft.Colors.RED, size=20), 
                            ft.Text("Anuluj i wróć")
                        ]), 
                        on_click=wroc
                    )
                ],
                tooltip="Opcje formularza"
            )
        )
    if akcje_dodatkowe:
        actions.extend(akcje_dodatkowe)

    return ft.AppBar(
        title=ft.Text(tytul, weight="bold", size=18),
        center_title=False,
        bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.PRIMARY),
        leading=ft.IconButton(
            icon=ft.Icons.ARROW_BACK,
            on_click=wroc
        ),
        actions=actions
    )

def _zbuduj_popup_filtra(page: ft.Page, state, klucz_stanu, opcje, etykieta, ikona_aktywna, ikona_nieaktywna):
    """Generyczna metoda budująca przycisk filtra z menu rozwijanym."""
    aktualny_filtr = state.filtry.setdefault(klucz_stanu, "Wszystko")
    if aktualny_filtr not in opcje:
        aktualny_filtr = "Wszystko"
        state.filtry[klucz_stanu] = aktualny_filtr

    def zmien_filtr(wartosc):
        state.filtry[klucz_stanu] = wartosc
        przejdz(page, page.route)

    elementy_menu = []
    for o in opcje:
        zaznaczone = (o == aktualny_filtr)
        elementy_menu.append(
            ft.PopupMenuItem(
                content=ft.Row([
                    ft.Icon(ft.Icons.CHECK, size=16, color=ft.Colors.PRIMARY, visible=zaznaczone),
                    ft.Text(o, weight="bold" if zaznaczone else "normal")
                ]),
                on_click=lambda e, val=o: zmien_filtr(val)
            )
        )

    jest_aktywny = (aktualny_filtr != "Wszystko")
    kolor_glowny = ft.Colors.PRIMARY if jest_aktywny else ft.Colors.ON_SURFACE_VARIANT
    kolor_tla = ft.Colors.with_opacity(0.15, ft.Colors.PRIMARY) if jest_aktywny else ft.Colors.with_opacity(0.06, ft.Colors.ON_SURFACE)

    pokazywany_tekst = aktualny_filtr if jest_aktywny else etykieta
    if len(pokazywany_tekst) > 9:
        pokazywany_tekst = pokazywany_tekst[:7] + ".."

    popup = ft.PopupMenuButton(
        items=elementy_menu,
        content=ft.Row([
            ft.Icon(ikona_aktywna if jest_aktywny else ikona_nieaktywna, size=13, color=kolor_glowny),
            ft.Text(pokazywany_tekst, size=11, weight="bold", color=kolor_glowny),
        ], spacing=2),
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

def przycisk_filtrowania_rok(page: ft.Page, state, klucz_stanu, lista_danych, index_daty):
    lata = set()
    for w in lista_danych:
        try:
            data_str = w[index_daty]
            d = parsuj_date(data_str)
            if d != datetime.min.date():
                lata.add(str(d.year))
        except Exception:
            pass
    
    opcje = ["Wszystko"] + sorted(list(lata), reverse=True)
    return _zbuduj_popup_filtra(
        page, state, klucz_stanu, opcje, "Rok",
        ft.Icons.FILTER_ALT_ROUNDED, ft.Icons.FILTER_ALT_OUTLINED
    )


def przycisk_filtrowania_kategoria(page: ft.Page, state, klucz_stanu, lista_danych, index_pola, etykieta="Tagi"):
    wartosci = set()
    for w in lista_danych:
        try:
            wartosc = str(w[index_pola] or "").strip()
            if wartosc and wartosc != "None":
                for tag in wartosc.split(","):
                    if tag.strip(): wartosci.add(tag.strip())
        except Exception:
            pass
    
    opcje = ["Wszystko"] + sorted(list(wartosci))
    return _zbuduj_popup_filtra(
        page, state, klucz_stanu, opcje, etykieta,
        ft.Icons.LABEL_ROUNDED, ft.Icons.LABEL_OUTLINE
    )


def przycisk_filtrowania_miesiac(page: ft.Page, state, klucz_stanu, lista_danych, index_daty):
    miesiace_nr = set()
    for w in lista_danych:
        try:
            data_str = w[index_daty]
            d = parsuj_date(data_str)
            if d != datetime.min.date():
                miesiace_nr.add(d.month)
        except Exception:
            pass
    
    opcje = ["Wszystko"] + [MIESIACE_NAZWY[m - 1] for m in sorted(list(miesiace_nr))]
    return _zbuduj_popup_filtra(
        page, state, klucz_stanu, opcje, "Miesiąc",
        ft.Icons.DATE_RANGE_ROUNDED, ft.Icons.DATE_RANGE_OUTLINED
    )

def filtruj_po_roku(lista_danych, state, klucz_stanu, index_daty):
    filtr = state.filtry.get(klucz_stanu, "Wszystko")
    if filtr == "Wszystko":
        return lista_danych
    
    wynik = []
    for w in lista_danych:
        try:
            data_str = w[index_daty]
            d = parsuj_date(data_str)
            if d != datetime.min.date() and str(d.year) == filtr:
                wynik.append(w)
        except Exception:
            pass
    return wynik

def filtruj_po_kategorii(lista_danych, state, klucz_stanu, index_pola):
    filtr = state.filtry.get(klucz_stanu, "Wszystko")
    if filtr == "Wszystko":
        return lista_danych
    
    wynik = []
    for w in lista_danych:
        try:
            wartosc = str(w[index_pola] or "").strip()
            tagi_w_rekordzie = [t.strip() for t in wartosc.split(",")]
            if filtr in tagi_w_rekordzie:
                wynik.append(w)
        except Exception:
            pass
    return wynik

def filtruj_po_miesiacu(lista_danych, state, klucz_stanu, index_daty):
    filtr = state.filtry.get(klucz_stanu, "Wszystko")
    if filtr == "Wszystko":
        return lista_danych
    
    idx_miesiaca = MIESIACE_NAZWY.index(filtr) + 1
    wynik = []
    for w in lista_danych:
        try:
            data_str = w[index_daty]
            d = parsuj_date(data_str)
            if d != datetime.min.date() and d.month == idx_miesiaca:
                wynik.append(w)
        except Exception:
            pass
    return wynik

def ekran_braku_danych(ikona, tytul, opis, tekst_przycisku, on_click):
    return ft.Container(
        padding=30,
        content=ft.Column([
            ft.Container(height=10),
            ft.Row([
                ft.Container(
                    width=104, height=104, border_radius=52,
                    alignment=ft.Alignment.CENTER,
                    gradient=ft.RadialGradient(colors=[
                        ft.Colors.with_opacity(0.22, ft.Colors.PRIMARY),
                        ft.Colors.with_opacity(0.0, ft.Colors.PRIMARY),
                    ]),
                    content=ft.Icon(ikona, size=46, color=ft.Colors.PRIMARY),
                )
            ], alignment=ft.MainAxisAlignment.CENTER),
            ft.Container(height=10),
            ft.Row([
                ft.Text(tytul, size=FS["heading"], weight="bold", color=ft.Colors.ON_SURFACE)
            ], alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([
                ft.Text(opis, size=FS["body"], color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER)
            ], alignment=ft.MainAxisAlignment.CENTER),
            ft.Container(height=15),
            ft.Row([
                ft.ElevatedButton(
                    content=ft.Row([
                        ft.Icon(ft.Icons.ADD, size=18, color=ft.Colors.ON_PRIMARY),
                        ft.Text(tekst_przycisku, color=ft.Colors.ON_PRIMARY, weight="bold")
                    ], tight=True, spacing=6),
                    bgcolor=ft.Colors.PRIMARY,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=RADIUS["md"]), padding=ft.Padding(20, 14, 20, 14)),
                    on_click=on_click
                )
            ], alignment=ft.MainAxisAlignment.CENTER),
            ft.Container(height=20)
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)
    )

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

def karta_formularza(zawartosc, tytul=None, ikona=None, domyslnie_otwarte=False, page: ft.Page = None):
    import flet as ft
    powierzchnia = powierzchnia_karty(page, "md")

    if not tytul:
        return ft.Container(
            padding=SPACING["lg"], border_radius=RADIUS["lg"],
            bgcolor=powierzchnia["bgcolor"], shadow=powierzchnia["shadow"],
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
        ikona_strzalki.name = ft.Icons.KEYBOARD_ARROW_UP if cialo.visible else ft.Icons.KEYBOARD_ARROW_DOWN
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
        content=ft.Column([naglowek, cialo], spacing=0)
    )

def przyciski_akcji(page: ft.Page, tekst_zapisu, on_zapisz, trasa_anuluj):
    btn_zapisz = ft.ElevatedButton(
        tekst_zapisu, 
        on_click=on_zapisz, 
        bgcolor=ft.Colors.PRIMARY, 
        color=ft.Colors.ON_PRIMARY, 
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=RADIUS["md"]), padding=15),
        width=float("inf")
    )
    btn_anuluj = ft.OutlinedButton(
        "Anuluj", 
        on_click=lambda e: przejdz(page, trasa_anuluj), 
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=RADIUS["md"]), padding=15),
        width=float("inf")
    )
    return ft.Column([ft.Divider(height=10, color="transparent"), btn_zapisz, btn_anuluj, dol_bezpieczny(30)], spacing=10)

def dol_bezpieczny(wysokosc=20):
    return ft.SafeArea(
        content=ft.Container(height=wysokosc),
        avoid_intrusions_top=False,
    )

def formatuj_spalanie(l_na_100km, decimale=1):
    jednostka = db.pobierz_jednostke_spalania()
    try:
        val = float(l_na_100km)
    except (TypeError, ValueError):
        return f"- {jednostka}"
    if val <= 0:
        return f"- {jednostka}"

    if jednostka == "km/l":
        wynik = 100.0 / val
    elif jednostka == "mpg":
        wynik = 235.214583 / val
    else:
        wynik = val

    return f"{formatuj_liczba(wynik, decimale)} {jednostka}"

def symbol_waluty():
    return db.pobierz_walute()

MIESIACE_DOPELNIACZ = [
    "stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
    "lipca", "sierpnia", "września", "października", "listopada", "grudnia"
]

def formatuj_date_pl(d):
    tekst = f"{d.day} {MIESIACE_DOPELNIACZ[d.month - 1]}"
    if d.year != datetime.now().year:
        tekst += f" {d.year}"
    return tekst

def oblicz_prognoze_terminu(zostalo_km, sredni_dzienny_przebieg):
    if not sredni_dzienny_przebieg or sredni_dzienny_przebieg <= 0:
        return None, None
    if zostalo_km is None or zostalo_km < 0:
        return None, None

    dni = int(round(zostalo_km / sredni_dzienny_przebieg))
    return dni, date.today() + timedelta(days=dni)

def formatuj_prognoze_km(zostalo_km, sredni_dzienny_przebieg):
    tekst_km = f"{formatuj_liczba(zostalo_km, 0)} km"

    dni, data = oblicz_prognoze_terminu(zostalo_km, sredni_dzienny_przebieg)
    if dni is None:
        return tekst_km

    if dni <= 0:
        opis_dni = "dziś"
    elif dni == 1:
        opis_dni = "jutro"
    else:
        opis_dni = f"ok. {dni} dni"

    return f"{tekst_km} ({opis_dni} - {formatuj_date_pl(data)})"

def kolor_i_tekst_terminu(termin_str):
    if not termin_str:
        return ft.Colors.ON_SURFACE_VARIANT, ""
        
    d_obj = parsuj_date(termin_str)
    if d_obj == datetime.min.date():
        return ft.Colors.ON_SURFACE_VARIANT, termin_str
        
    dzis = datetime.now().date()
    roznica = (d_obj - dzis).days
    
    if roznica < 0:
        return ft.Colors.RED_700, f"Po terminie ({abs(roznica)} dni)"
    elif roznica == 0:
        return ft.Colors.RED_700, "Na dzisiaj!"
    elif roznica == 1:
        return ft.Colors.ORANGE_700, "Na jutro"
    elif roznica <= 7:
        return ft.Colors.ORANGE_700, f"Za {roznica} dni"
    else:
        return ft.Colors.GREEN_700, str(termin_str)

def komponent_wyboru_koloru(page: ft.Page, aktualny_kolor=None, etykieta_brak="Domyślny (jak w Ustawieniach)"):
    """Wiersz kółek do wyboru koloru motywu interfejsu, z dodatkową pozycją
    'Brak' (użyje wtedy globalnego koloru domyślnego). Zwraca (kontener,
    pobierz_wynik), gdzie pobierz_wynik() zwraca nazwę koloru z db.KOLORY_MOTYWU
    albo None."""
    stan = {"wybrany": aktualny_kolor if aktualny_kolor in db.KOLORY_MOTYWU else None}
    wiersz = ft.Row(wrap=True, spacing=10)

    def wybierz(nazwa):
        stan["wybrany"] = nazwa
        odswiez()

    def odswiez():
        wiersz.controls.clear()

        zaznaczony_brak = stan["wybrany"] is None
        wiersz.controls.append(
            ft.Container(
                width=45, height=45, shape=ft.BoxShape.CIRCLE,
                bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE),
                border=ft.Border.all(3, ft.Colors.ON_SURFACE if zaznaczony_brak else ft.Colors.TRANSPARENT),
                alignment=ft.Alignment.CENTER,
                content=ft.Icon(ft.Icons.BLOCK, size=20, color=ft.Colors.ON_SURFACE_VARIANT),
                tooltip=etykieta_brak,
                on_click=lambda e: wybierz(None)
            )
        )

        for nazwa in db.KOLORY_MOTYWU:
            kolor_hex = MAPA_KOLOROW.get(nazwa, ft.Colors.INDIGO)
            zaznaczony = (stan["wybrany"] == nazwa)
            wiersz.controls.append(
                ft.Container(
                    width=45, height=45, bgcolor=kolor_hex, shape=ft.BoxShape.CIRCLE,
                    border=ft.Border.all(3, ft.Colors.ON_SURFACE if zaznaczony else ft.Colors.TRANSPARENT),
                    content=ft.Icon(ft.Icons.CHECK, color=ft.Colors.WHITE, size=24) if zaznaczony else None,
                    tooltip=nazwa,
                    on_click=lambda e, n=nazwa: wybierz(n)
                )
            )

        try:
            wiersz.update()
        except Exception:
            pass

    odswiez()
    return wiersz, lambda: stan["wybrany"]

def komponent_tagow(page: ft.Page, state, aktualne_tagi_str):
    wybrane = set([t.strip() for t in (aktualne_tagi_str or "").split(",") if t.strip()])
    kontener_tagow = ft.Row(wrap=True, spacing=8)
    
    def odswiez_tagi():
        kontener_tagow.controls.clear()
        wszystkie = db.pobierz_tagi(state.auto_id)
        
        for t_id, nazwa, kolor in wszystkie:
            zaznaczony = nazwa in wybrane
            kolor_hex = MAPA_KOLOROW.get(kolor, ft.Colors.BLUE)
            
            # --- DODANE: Funkcja do edycji i trwałego usuwania taga z bazy ---
            def stworz_akcje_opcji(tid, tn, aktualny_kolor):
                def akcja(e):
                    e_nazwa = ft.TextField(label="Nazwa tagu", value=tn, **styl_pola())
                    e_kolor = ft.Dropdown(
                        label="Kolor tagu", 
                        options=[ft.DropdownOption(k) for k in MAPA_KOLOROW.keys()],
                        value=aktualny_kolor,
                        **styl_dropdown()
                    )
                    
                    def zapisz_zmiany(e_btn):
                        e_nazwa.error_text = None
                        nowa_nazwa = (e_nazwa.value or "").strip()
                        
                        if "," in nowa_nazwa:
                            e_nazwa.error_text = "Nazwa nie może zawierać przecinków"
                            e_nazwa.update()
                            return

                        if nowa_nazwa:
                            db.edytuj_tag_w_slowniku(state.auto_id, tid, tn, nowa_nazwa, e_kolor.value)
                            if tn in wybrane:
                                wybrane.remove(tn)
                                wybrane.add(nowa_nazwa)
                            zamknij_dialog(page, dlg)
                            odswiez_tagi()
                            
                    def usun_tag(e_btn):
                        def wykonaj():
                            db.usun_tag_ze_slownika(state.auto_id, tid, tn)
                            if tn in wybrane: wybrane.remove(tn)
                            odswiez_tagi()
                        zamknij_dialog(page, dlg)
                        potwierdz(page, "Usuń tag", f"Usunąć '{tn}'? Zniknie ze wszystkich historycznych wpisów.", wykonaj)

                    dlg = ft.AlertDialog(
                        title=ft.Text(f"Opcje tagu: {tn}", weight="bold"),
                        content=ft.Column([e_nazwa, e_kolor], tight=True, spacing=10),
                        actions=[
                            ft.TextButton("Usuń", style=ft.ButtonStyle(color=ft.Colors.RED_700), on_click=usun_tag),
                            ft.TextButton("Anuluj", on_click=lambda e: zamknij_dialog(page, dlg)),
                            ft.ElevatedButton("Zapisz", on_click=zapisz_zmiany, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY)
                        ]
                    )
                    otworz_dialog(page, dlg)
                return akcja

            chip = ft.Container(
                content=ft.Text(nazwa, size=FS["label"], color=ft.Colors.WHITE if zaznaczony else kolor_hex, weight="bold"),
                padding=ft.Padding(12, 6, 12, 6),
                border_radius=RADIUS["pill"],
                bgcolor=kolor_hex if zaznaczony else ft.Colors.with_opacity(0.12, kolor_hex),
                on_click=lambda e, n=nazwa: przelacz_tag(n),
                on_long_press=stworz_akcje_opcji(t_id, nazwa, kolor),
                tooltip="Kliknij: Zaznacz | Przytrzymaj: Edytuj / Usuń"
            )
            kontener_tagow.controls.append(chip)
            
        btn_dodaj = ft.Container(
            content=ft.Row([ft.Icon(ft.Icons.ADD, size=14, color=ft.Colors.ON_SURFACE_VARIANT), ft.Text("Nowy", size=FS["label"], color=ft.Colors.ON_SURFACE_VARIANT)], spacing=4),
            padding=ft.Padding(12, 6, 12, 6),
            border_radius=RADIUS["pill"],
            bgcolor=tlo_karty(page, poziom=2),
            on_click=lambda e: okno_nowego_tagu()
        )
        kontener_tagow.controls.append(btn_dodaj)
        try:
            kontener_tagow.update()
        except Exception:
            pass
        
    def przelacz_tag(nazwa):
        if nazwa in wybrane:
            wybrane.remove(nazwa)
        else:
            wybrane.add(nazwa)
        odswiez_tagi()
        
    def okno_nowego_tagu():
        e_nazwa = ft.TextField(label="Nazwa tagu", **styl_pola())
        e_kolor = ft.Dropdown(
            label="Kolor tagu", 
            options=[ft.DropdownOption(k) for k in MAPA_KOLOROW.keys()],
            value="Niebieski",
            **styl_dropdown()
        )
        def zapisz_nowy(e):
            e_nazwa.error_text = None
            n = (e_nazwa.value or "").strip()
            
            if "," in n:
                e_nazwa.error_text = "Nazwa nie może zawierać przecinków"
                e_nazwa.update()
                return

            if n:
                db.dodaj_tag(state.auto_id, n, e_kolor.value)
                wybrane.add(n)
                zamknij_dialog(page, dlg)
                odswiez_tagi()
                
        dlg = ft.AlertDialog(
            title=ft.Text("Utwórz nowy tag", weight="bold"),
            content=ft.Column([e_nazwa, e_kolor], tight=True, spacing=10),
            actions=[
                ft.TextButton("Anuluj", on_click=lambda e: zamknij_dialog(page, dlg)),
                ft.ElevatedButton("Dodaj", on_click=zapisz_nowy, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY)
            ]
        )
        otworz_dialog(page, dlg)
        
    odswiez_tagi()
    return kontener_tagow, lambda: ",".join(wybrane)

def wizualizacja_tagow(tagi_str, auto_id, mapa_kolorow=None):
    if not tagi_str or str(tagi_str).strip() == "None":
        return ft.Container()

    wszystkie_kolory = mapa_kolorow if mapa_kolorow is not None else {t[1]: t[2] for t in db.pobierz_tagi(auto_id)}
    tagi_lista = [t.strip() for t in str(tagi_str).split(",") if t.strip()]
    
    chipy = []
    for t in tagi_lista:
        kolor_nazwa = wszystkie_kolory.get(t, "Niebieski")
        kolor_hex = MAPA_KOLOROW.get(kolor_nazwa, ft.Colors.BLUE)
        
        chipy.append(
            ft.Container(
                content=ft.Text(t, size=FS["caption"], weight="bold", color=kolor_hex),
                padding=ft.Padding(8, 3, 8, 3),
                border_radius=RADIUS["pill"],
                bgcolor=ft.Colors.with_opacity(0.12, kolor_hex),
            )
        )
    return ft.Row(chipy, wrap=True, spacing=4)

def znacznik_atrybucji(dodane_przez, zmodyfikowane_przez=None, data_modyfikacji=None):
    """Dyskretny 'chip' pokazujący kto dodał wpis i — jeśli był edytowany —
    kto i kiedy go ostatnio zmienił. Używany tylko przy współdzielonych
    pojazdach, gdzie mogła to zrobić inna osoba."""
    if not dodane_przez and not zmodyfikowane_przez:
        return ft.Container()

    fragmenty = []
    if dodane_przez:
        fragmenty.append(f"Dodano: {dodane_przez}")
    if zmodyfikowane_przez:
        data_txt = f" ({data_modyfikacji})" if data_modyfikacji else ""
        fragmenty.append(f"Edytowano: {zmodyfikowane_przez}{data_txt}")

    return ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.PERSON_OUTLINE, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Text(" | ".join(fragmenty), size=11, color=ft.Colors.ON_SURFACE_VARIANT),
        ], spacing=4),
    )

def znacznik_dodane_przez(nazwa):
    """Mały, dyskretny 'chip' pokazujący kto dodał wpis — używany tylko przy
    współdzielonych pojazdach, gdzie mogła to zrobić inna osoba."""
    if not nazwa:
        return ft.Container(width=0, height=0)
    return ft.Container(
        padding=ft.Padding(6, 2, 6, 2),
        border_radius=6,
        bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.TEAL_700),
        content=ft.Row([
            ft.Icon(ft.Icons.PERSON, size=10, color=ft.Colors.TEAL_700),
            ft.Text(str(nazwa), size=10, weight="bold", color=ft.Colors.TEAL_700)
        ], spacing=3, tight=True)
    )

def komponent_wyboru_warsztatu(page: ft.Page, state, aktualna_nazwa=""):
    stan = {"telefon": None, "adres": None}
    cache_warsztatow = {"dane": None}

    def wpisy_warsztatow():
        # Cache w obrębie życia tego komponentu — lista warsztatów nie
        # zmienia się, dopóki formularz jest otwarty, więc wystarczy jeden SELECT.
        if cache_warsztatow["dane"] is None:
            cache_warsztatow["dane"] = db.pobierz_warsztaty(state.auto_id)
        return cache_warsztatow["dane"]

    warsztaty = wpisy_warsztatow()
    pasujacy_start = next((w for w in warsztaty if w[1] == aktualna_nazwa), None) if aktualna_nazwa else None
    
    # Tryb ręczny włączony tylko gdy wczytujemy wpis, którego nie ma w bazie
    pokaz_reczne = bool(aktualna_nazwa and not pasujacy_start)

    def zbuduj_opcje():
        opcje = [ft.DropdownOption(key="", text="— Brak przypisanego —")]
        for w_id, w_nazwa, w_tel, w_adr, w_not in wpisy_warsztatow():
            opcje.append(ft.DropdownOption(key=w_nazwa, text=w_nazwa))
        return opcje

    e_dropdown = ft.Dropdown(
        label="Warsztat / Wykonawca",
        options=zbuduj_opcje(),
        value=aktualna_nazwa if pasujacy_start else "",
        visible=not pokaz_reczne,
        expand=True,
        **styl_dropdown()
    )

    e_recznie = ft.TextField(
        label="Wpisz nazwę (zapisze się automatycznie)",
        value=aktualna_nazwa if pokaz_reczne else "",
        visible=pokaz_reczne,
        expand=True,
        **styl_pola()
    )

    btn_zmien_tryb = ft.IconButton(
        icon=ft.Icons.LIST if pokaz_reczne else ft.Icons.EDIT,
        tooltip="Wybierz warsztat z bazy" if pokaz_reczne else "Wpisz nową nazwę ręcznie",
        icon_color=ft.Colors.PRIMARY
    )

    wiersz_glowne = ft.Row([e_dropdown, e_recznie, btn_zmien_tryb], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=10)

    btn_dzwon = ft.OutlinedButton("📞 Zadzwoń", visible=False)
    btn_nawiguj = ft.OutlinedButton("🧭 Nawiguj", visible=False)
    wiersz_akcji = ft.Row([btn_dzwon, btn_nawiguj], spacing=8, visible=False)

    async def zadzwon(e):
        if stan["telefon"]: await page.launch_url(f"tel:{stan['telefon']}")

    async def nawiguj(e):
        if stan["adres"]: await page.launch_url(f"geo:0,0?q={urllib.parse.quote(stan['adres'])}")

    btn_dzwon.on_click = zadzwon
    btn_nawiguj.on_click = nawiguj

    def odswiez_akcje():
        btn_dzwon.visible = bool(stan["telefon"] and e_dropdown.visible)
        btn_nawiguj.visible = bool(stan["adres"] and e_dropdown.visible)
        wiersz_akcji.visible = btn_dzwon.visible or btn_nawiguj.visible
        try: wiersz_akcji.update()
        except Exception: pass

    def przelacz_tryb(e):
        na_reczne = not e_recznie.visible
        if na_reczne:
            e_dropdown.visible = False
            e_dropdown.value = ""
            e_recznie.visible = True
            btn_zmien_tryb.icon = ft.Icons.LIST
            btn_zmien_tryb.tooltip = "Wybierz z bazy"
        else:
            e_recznie.visible = False
            e_recznie.value = ""
            e_dropdown.visible = True
            btn_zmien_tryb.icon = ft.Icons.EDIT
            btn_zmien_tryb.tooltip = "Wpisz ręcznie"
            e_dropdown.value = ""
            stan["telefon"], stan["adres"] = None, None

        odswiez_akcje()
        try: wiersz_glowne.update()
        except Exception: pass
        
    btn_zmien_tryb.on_click = przelacz_tryb

    def ustaw_z_bazy(nazwa):
        pasujacy = next((w for w in wpisy_warsztatow() if w[1] == nazwa), None)
        if pasujacy:
            stan["telefon"], stan["adres"] = pasujacy[2], pasujacy[3]
        else:
            stan["telefon"], stan["adres"] = None, None
        
        e_dropdown.options = zbuduj_opcje()
        e_dropdown.value = nazwa if pasujacy else ""
        odswiez_akcje()
        try: e_dropdown.update()
        except Exception: pass

    def po_zmianie(e):
        wart = e_dropdown.value
        if wart == "":
            stan["telefon"], stan["adres"] = None, None
            odswiez_akcje()
            try: e_dropdown.update()
            except Exception: pass
        else:
            ustaw_z_bazy(wart)

    e_dropdown.on_change = po_zmianie
    
    if pasujacy_start and not pokaz_reczne:
        stan["telefon"], stan["adres"] = pasujacy_start[2], pasujacy_start[3]
        odswiez_akcje()

    kontener = ft.Column([wiersz_glowne, wiersz_akcji], spacing=4)

    def pobierz_wynik():
        if e_recznie.visible:
            return (e_recznie.value or "").strip()
        wart = e_dropdown.value
        if wart in ("", None):
            return ""
        return wart

    return kontener, pobierz_wynik

def abs_zalacznik(sciezka_wzgledna):
    if not sciezka_wzgledna:
        return None
    return os.path.abspath(sciezka_wzgledna)

def komponent_zalacznika(page: ft.Page, sciezka_zapisana=None, tylko_zdjecie=False):
    """tylko_zdjecie=True wymusza pojedynczy plik (zdjęcie profilowe pojazdu,
    pojedyncze zdjęcie w galerii karoserii) — bez wielokrotnego wyboru.
    Domyślnie (False) pozwala zaznaczyć od razu kilka zdjęć naraz — zostaną
    automatycznie połączone w jeden wielostronicowy PDF (np. kilka stron
    faktury/paragonu)."""
    stan = {"nowa_sciezka": None, "usuniete": False}
    obsluzono = {"wartosc": False}  # zabezpiecza przed podwójnym zadziałaniem on_result + await

    def zawartosc_podgladu(sciezka):
        if sciezka:
            if sciezka.lower().endswith(".pdf"):
                return ft.Icon(ft.Icons.PICTURE_AS_PDF, size=32, color=ft.Colors.RED_700)
            return ft.Image(src=sciezka, width=56, height=56, fit="cover", border_radius=10)
        return ft.Icon(ft.Icons.IMAGE_OUTLINED, size=26, color=ft.Colors.ON_SURFACE_VARIANT)

    ramka_podgladu = ft.Container(
        width=56, height=56, border_radius=10, alignment=ft.Alignment.CENTER,
        bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.ON_SURFACE),
        content=zawartosc_podgladu(abs_zalacznik(sciezka_zapisana))
    )
    tekst_nazwy = ft.Text(
        os.path.basename(sciezka_zapisana) if sciezka_zapisana else "Brak załącznika",
        size=13, color=ft.Colors.ON_SURFACE_VARIANT, expand=True
    )
    btn_usun = ft.IconButton(
        icon=ft.Icons.DELETE_OUTLINE, icon_color=ft.Colors.RED_700,
        tooltip="Usuń załącznik", visible=bool(sciezka_zapisana)
    )

    def odswiez(sciezka_podgladu, etykieta, pokazuj_usun):
        ramka_podgladu.content = zawartosc_podgladu(sciezka_podgladu)
        tekst_nazwy.value = etykieta
        btn_usun.visible = pokazuj_usun
        try:
            page.update()
        except Exception:
            pass

    def _obsluz_wybrane(pliki):
        """Wspólna logika dla on_result i ścieżki await — działa i dla 1, i dla wielu plików."""
        if not pliki:
            return
        sciezki = [p.path for p in pliki if getattr(p, "path", None)]
        if not sciezki:
            pokaz_komunikat(page, "Brak dostępu do ścieżki (Uprawnienia telefonu).", ft.Colors.RED_700)
            return

        if len(sciezki) == 1:
            stan["nowa_sciezka"] = sciezki[0]
            stan["usuniete"] = False
            odswiez(sciezki[0], os.path.basename(sciezki[0]), True)
            return

        if any(s.lower().endswith(".pdf") for s in sciezki):
            pokaz_komunikat(page, "Można połączyć wiele zdjęć w jeden PDF, ale nie plik PDF razem ze zdjęciami — wybierz same zdjęcia.", ft.Colors.ORANGE_700)
            return

        polaczony = db.polacz_zdjecia_w_pdf(sciezki)
        if not polaczony:
            pokaz_komunikat(page, "Nie udało się połączyć wybranych zdjęć w PDF.", ft.Colors.RED_700)
            return

        stan["nowa_sciezka"] = polaczony
        stan["usuniete"] = False
        odswiez(polaczony, f"{len(sciezki)} zdjęć połączonych w PDF", True)

    def po_wyborze(e):
        if obsluzono["wartosc"]:
            return
        obsluzono["wartosc"] = True
        _obsluz_wybrane(getattr(e, "files", None))

    async def wybierz(e):
        obsluzono["wartosc"] = False
        page.zalacznik_picker.on_result = po_wyborze
        page.zalacznik_picker.update()

        try:
            wynik = await page.zalacznik_picker.pick_files(
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["jpg", "jpeg", "png", "webp", "pdf"],
                allow_multiple=not tylko_zdjecie
            )
            if wynik is not None and not obsluzono["wartosc"]:
                obsluzono["wartosc"] = True
                pliki = getattr(wynik, "files", wynik)
                _obsluz_wybrane(pliki if isinstance(pliki, list) else None)
        except Exception as ex:
            pokaz_komunikat(page, f"Błąd wczytywania pliku: {ex}", ft.Colors.RED_700)

    def usun(e):
        stan["nowa_sciezka"] = None
        stan["usuniete"] = True
        odswiez(None, "Brak załącznika", False)

    btn_usun.on_click = usun

    wiersz = ft.Row([ramka_podgladu, tekst_nazwy, btn_usun], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=10)
    etykieta_przycisku = (
        "📎 Dodaj / zmień załącznik (zdjęcie, PDF)" if tylko_zdjecie
        else "📎 Dodaj / zmień załącznik (możesz zaznaczyć kilka zdjęć naraz)"
    )
    btn_wybierz = ft.TextButton(etykieta_przycisku, on_click=wybierz)

    kontener = ft.Column([wiersz, btn_wybierz], spacing=8)

    def pobierz_wynik():
        if stan["usuniete"]:
            return ""
        if stan["nowa_sciezka"]:
            return stan["nowa_sciezka"]
        return None

    return kontener, pobierz_wynik

def komponent_wielu_nowych_zdjec(page: ft.Page):
    """Widget do MASOWEGO dodawania nowych zdjęć (np. galeria karoserii): pozwala
    zaznaczyć od razu kilka plików i dobierać kolejne w kilku turach (nowe pliki
    dopisują się do listy, nie zastępują jej). Zwraca (kontrolka, pobierz_wynik),
    gdzie pobierz_wynik() to lista ścieżek źródłowych — jeszcze niezapisanych
    do trwałego magazynu (kopiowanie robi się dopiero przy zapisie formularza)."""
    stan = {"pliki": []}
    obsluzono = {"wartosc": False}
    lista_podgladow = ft.Column(spacing=8)
    licznik = ft.Text("Nie wybrano jeszcze żadnego zdjęcia.", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

    def usun(sciezka):
        stan["pliki"] = [s for s in stan["pliki"] if s != sciezka]
        odswiez()

    def odswiez():
        lista_podgladow.controls.clear()
        for sciezka in stan["pliki"]:
            lista_podgladow.controls.append(
                ft.Row([
                    ft.Container(
                        width=52, height=52, border_radius=8,
                        content=ft.Image(src=sciezka, width=52, height=52, fit="cover", border_radius=8),
                    ),
                    ft.Text(os.path.basename(sciezka), size=12, color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                    ft.IconButton(icon=ft.Icons.CLOSE, icon_size=18, icon_color=ft.Colors.RED_700, on_click=lambda e, s=sciezka: usun(s)),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=10)
            )
        n = len(stan["pliki"])
        licznik.value = "Nie wybrano jeszcze żadnego zdjęcia." if n == 0 else f"Wybrano zdjęć: {n}"
        try:
            lista_podgladow.update()
            licznik.update()
        except Exception:
            pass

    def dodaj_pliki(pliki):
        if not pliki:
            return
        rozszerzenia = (".jpg", ".jpeg", ".png", ".webp")
        nowe = [p.path for p in pliki if getattr(p, "path", None) and p.path.lower().endswith(rozszerzenia)]
        pominieto_pdf = any(getattr(p, "path", "").lower().endswith(".pdf") for p in pliki if getattr(p, "path", None))

        if nowe:
            for s in nowe:
                if s not in stan["pliki"]:
                    stan["pliki"].append(s)
            odswiez()
        if pominieto_pdf:
            pokaz_komunikat(page, "Pliki PDF pominięto — galeria karoserii przyjmuje tylko zdjęcia.", ft.Colors.ORANGE_700)
        elif not nowe:
            pokaz_komunikat(page, "Brak dostępu do wybranych plików (uprawnienia).", ft.Colors.RED_700)

    def po_wyborze(e):
        obsluzono["wartosc"] = True
        dodaj_pliki(getattr(e, "files", None))

    async def wybierz(e):
        obsluzono["wartosc"] = False
        page.zalacznik_picker.on_result = po_wyborze
        page.zalacznik_picker.update()
        try:
            wynik = await page.zalacznik_picker.pick_files(
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["jpg", "jpeg", "png", "webp"],
                allow_multiple=True,
            )
            if wynik is not None and not obsluzono["wartosc"]:
                dodaj_pliki(getattr(wynik, "files", wynik))
        except Exception as ex:
            pokaz_komunikat(page, f"Błąd wczytywania plików: {ex}", ft.Colors.RED_700)

    btn_dodaj = ft.TextButton("📷 Wybierz zdjęcia (można zaznaczyć od razu kilka)", on_click=wybierz)
    kontener = ft.Column([btn_dodaj, licznik, lista_podgladow], spacing=8)
    return kontener, lambda: list(stan["pliki"])

def pokaz_podglad_zalacznika(page: ft.Page, sciezka_wzgledna, tytul="Załącznik"):
    if not sciezka_wzgledna:
        return
        
    abs_path = abs_zalacznik(sciezka_wzgledna)
    
        # 1. Obsługa plików PDF — używamy systemowego arkusza udostępniania (Share)
    # zamiast page.launch_url() na surowe URI "file://", bo Android
    # (FileUriExposedException) i iOS (piaskownica aplikacji) coraz częściej
    # trwale blokują taki bezpośredni dostęp do lokalnego pliku.
    if abs_path.lower().endswith(".pdf"):
        async def otworz_pdf():
            serwis = getattr(page, "share_service", None)
            if serwis is not None:
                try:
                    if hasattr(serwis, "share_files_async"):
                        await serwis.share_files_async([abs_path])
                    else:
                        wynik = serwis.share_files([abs_path])
                        if asyncio.iscoroutine(wynik):
                            await wynik
                    return
                except Exception:
                    pass

            # Fallback dla środowisk bez usługi Share (np. desktop)
            try:
                import pathlib
                await page.launch_url(pathlib.Path(abs_path).as_uri())
            except Exception:
                pokaz_komunikat(page, "Nie można otworzyć pliku PDF na tym urządzeniu.", ft.Colors.RED_700)

        page.run_task(otworz_pdf)
        return
        
    # 2. Pełnoekranowy podgląd zdjęcia z możliwością przybliżania (pinch-to-zoom)
    import flet as ft
    img = ft.Image(src=abs_path, fit="contain") 
    
    viewer = ft.InteractiveViewer(
        min_scale=1.0, 
        max_scale=5.0, 
        boundary_margin=ft.Margin.all(0),
        content=img
    )
    
    # Tworzymy dialog na pełen ekran
    dlg = ft.AlertDialog(
        content_padding=0,
        inset_padding=0,
        title_padding=0,
        actions_padding=0,
        bgcolor=ft.Colors.BLACK,
        content=ft.Container(
            width=10000,
            height=10000,
            content=ft.Stack([
                ft.Container(content=viewer, alignment=ft.Alignment.CENTER, expand=True),
                # Zgrabny, "pływający" przycisk zamknięcia w rogu
                ft.Container(
                    content=ft.IconButton(
                        icon=ft.Icons.CLOSE, 
                        icon_color=ft.Colors.WHITE, 
                        icon_size=30,
                        bgcolor=ft.Colors.with_opacity(0.3, ft.Colors.BLACK),
                        on_click=lambda e: zamknij_dialog(page, dlg)
                    ),
                    top=20, 
                    right=20
                )
            ])
        )
    )
    otworz_dialog(page, dlg)

def wskaznik_zalacznika(page: ft.Page, sciezka_wzgledna, tytul="Załącznik"):
    if not sciezka_wzgledna:
        return ft.Container(width=0, height=0)
        
    czy_pdf = sciezka_wzgledna.lower().endswith(".pdf")
    ikona = ft.Icons.PICTURE_AS_PDF if czy_pdf else ft.Icons.IMAGE
    kolor = ft.Colors.RED_700 if czy_pdf else ft.Colors.PRIMARY
    
    return ft.Container(
        width=28, height=28, border_radius=8,
        bgcolor=ft.Colors.with_opacity(0.12, kolor),
        alignment=ft.Alignment.CENTER,
        tooltip="Pokaż załącznik",
        content=ft.Icon(ikona, size=15, color=kolor),
        on_click=lambda e: pokaz_podglad_zalacznika(page, sciezka_wzgledna, tytul),
    )

def wskaznik_kondycji(wynik):
    """Zwraca (kolor, ikona, etykieta) dla wskaźnika kondycji pojazdu (0-100)."""
    if wynik is None:
        return ft.Colors.ON_SURFACE_VARIANT, ft.Icons.HELP_OUTLINE, "Brak danych"
    if wynik >= 80:
        return ft.Colors.GREEN_700, ft.Icons.FAVORITE, "Bardzo dobra"
    if wynik >= 50:
        return ft.Colors.ORANGE_700, ft.Icons.FAVORITE_BORDER, "Wymaga uwagi"
    return ft.Colors.RED_700, ft.Icons.HEART_BROKEN, "Wymaga pilnej reakcji"

async def szybkie_dodanie_zdjecia(page: ft.Page, tabela: str, rekord_id: int, stara_sciezka, po_zapisie_callback):
    obsluzone = {"wartosc": False}

    def zapisz_wybrany_plik(plik):
        if obsluzone["wartosc"]:
            return
        obsluzone["wartosc"] = True
        nowy = db.zapisz_zalacznik(plik.path)
        db.usun_plik_zalacznika(stara_sciezka)
        with db.polacz_baze() as conn:
            conn.execute(f"UPDATE {tabela} SET zalacznik=? WHERE id=?", (nowy, rekord_id))
        pokaz_komunikat(page, "Zapisano zdjęcie!")
        po_zapisie_callback()

    def po_wyborze(e):
        pliki = getattr(e, "files", None)
        if pliki and len(pliki) > 0:
            plik = pliki[0]
            if getattr(plik, "path", None):
                zapisz_wybrany_plik(plik)
            else:
                pokaz_komunikat(page, "Brak dostępu do pliku (uprawnienia).", ft.Colors.RED_700)

    page.zalacznik_picker.on_result = po_wyborze
    page.zalacznik_picker.update() 
    
    try:
        wynik = await page.zalacznik_picker.pick_files(
            file_type=ft.FilePickerFileType.CUSTOM, 
            allowed_extensions=["jpg", "jpeg", "png", "webp", "pdf"],
            allow_multiple=False
        )
        
        if wynik is not None:
            pliki = getattr(wynik, "files", wynik)
            if isinstance(pliki, list) and len(pliki) > 0:
                plik = pliki[0]
                if getattr(plik, "path", None):
                    zapisz_wybrany_plik(plik)
                else:
                    pokaz_komunikat(page, "Brak dostępu do pliku (uprawnienia).", ft.Colors.RED_700)
    except Exception as ex:
        pokaz_komunikat(page, f"Błąd wczytywania: {ex}", ft.Colors.RED_700)

def karta_listy(tresc, kolor_paska=None, tlo=None, page=None):
    """Standardowa karta pozycji na liście, opcjonalnie z kolorowym paskiem
    statusu/priorytetu po lewej stronie. Zwraca (karta, kontener) — dokładnie
    jak dotychczas, karta.content nadal wskazuje na to samo, więc istniejące
    triki typu `karta.content.opacity = ...` działają bez zmian.
    Kontener ma już gotową (ale nieaktywną) animację naciśnięcia —
    zobacz `z_efektem_nacisniecia` niżej."""
    powierzchnia = powierzchnia_karty(page, "sm")
    tlo_finalne = tlo if tlo is not None else powierzchnia["bgcolor"]

    kontener = ft.Container(
        padding=SPACING["md"], ink=True,
        border_radius=0 if kolor_paska else RADIUS["lg"],
        bgcolor=tlo_finalne,
        expand=True if kolor_paska else None,
        scale=1.0,
        animate_scale=ft.Animation(120, ft.AnimationCurve.EASE_OUT),
        content=tresc if isinstance(tresc, ft.Control) else ft.Column(tresc, spacing=SPACING["xs"]),
    )

    if not kolor_paska:
        karta = ft.Container(
            border_radius=RADIUS["lg"],
            shadow=powierzchnia["shadow"],
            content=kontener,
        )
        return karta, kontener

    karta = ft.Container(
        border_radius=RADIUS["lg"], clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        shadow=powierzchnia["shadow"],
        content=ft.Row([ft.Container(width=4, bgcolor=kolor_paska), kontener], spacing=0),
    )
    return karta, kontener

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

def z_efektem_nacisniecia(kontener: ft.Container, funkcja):
    """Owija istniejący handler (on_click / on_long_press) tym samym efektem
    'naciśnięcia' co `fab_animowany` — karta na chwilę się zmniejsza i wraca.
    `kontener` musi pochodzić z `karta_listy` (ma już scale/animate_scale).
    W widoku, zamiast:
        kontener.on_click = _on_click
    użyj:
        kontener.on_click = utils.z_efektem_nacisniecia(kontener, _on_click)"""
    async def wrapper(e):
        kontener.scale = 0.97
        kontener.update()
        await asyncio.sleep(0.08)
        kontener.scale = 1.0
        kontener.update()
        wynik = funkcja(e)
        if asyncio.iscoroutine(wynik):
            await wynik
    return wrapper

def z_odswiezaniem(page: ft.Page, kontrolki: list, funkcja_odswiez=None):
    """Owija kontrolki widoku w przewijaną kolumnę z przyciskiem odświeżania.
    
    Zwraca gotową kontrolkę — do użycia jako JEDYNY element w super().__init__(
    controls=[...]), bez ustawiania scroll= na samym Widoku.
    """
    spinner = ft.ProgressRing(visible=False, width=18, height=18, stroke_width=2)
    btn_odswiez = ft.IconButton(
        icon=ft.Icons.REFRESH,
        tooltip="Odśwież widok",
        icon_size=20,
    )

    async def _wykonaj_odswiezenie(e):
        spinner.visible = True
        btn_odswiez.disabled = True
        page.update()

        try:
            handler = funkcja_odswiez or (lambda ev: przejdz(page, page.route))
            if inspect.iscoroutinefunction(handler):
                await handler(e)
            else:
                handler(e)
        finally:
            spinner.visible = False
            btn_odswiez.disabled = False
            page.update()

    btn_odswiez.on_click = _wykonaj_odswiezenie

    pasek_gora = ft.Row(
        controls=[spinner, btn_odswiez],
        alignment=ft.MainAxisAlignment.END,
    )

    return ft.Column(
        controls=[pasek_gora, *kontrolki],
        spacing=15,
        scroll=ft.ScrollMode.ALWAYS,
        expand=True,
    )

def segmented_control(page: ft.Page, opcje, aktywny_idx, on_zmiana):
    """Animowany zamiennik powtarzanego wzorca 'btn_zakladki' — segmenty
    przełączają się płynną animacją koloru i skali zamiast twardego przeskoku.
    opcje: lista (etykieta, indeks). on_zmiana(nowy_idx) wywoływane po kliknięciu."""
    segmenty = []
    for etykieta, idx in opcje:
        aktywny = (idx == aktywny_idx)
        segmenty.append(
            ft.Container(
                expand=True, height=36, alignment=ft.Alignment.CENTER,
                border_radius=RADIUS["pill"], ink=True,
                bgcolor=ft.Colors.PRIMARY if aktywny else ft.Colors.TRANSPARENT,
                animate=ft.Animation(220, ft.AnimationCurve.EASE_OUT),
                animate_scale=ft.Animation(220, ft.AnimationCurve.EASE_OUT),
                scale=1.0 if aktywny else 0.96,
                on_click=lambda e, i=idx: on_zmiana(i),
                content=ft.Text(
                    etykieta, size=FS["label"], weight="bold",
                    color=ft.Colors.ON_PRIMARY if aktywny else ft.Colors.ON_SURFACE_VARIANT,
                ),
            )
        )
    return ft.Container(
        padding=4, border_radius=RADIUS["pill"], bgcolor=tlo_karty(page, poziom=2),
        content=ft.Row(segmenty, spacing=4),
    )

def fab_speed_dial(page: ft.Page, akcje, ikona_glowna=ft.Icons.ADD, tooltip="Szybkie akcje"):
    """FAB „rozwijany” (speed-dial): dotknięcie głównego przycisku odsłania
    pionowy stos mniejszych przycisków z opisanymi szybkimi akcjami, zamiast
    pojedynczego przejścia do jednego formularza. `akcje`: lista krotek
    (ikona, etykieta, on_click) — on_click przyjmuje `e` jak zwykły on_click,
    może być sync albo async. Menu zamyka się automatycznie po wybraniu
    dowolnej akcji albo ponownym dotknięciu głównego przycisku."""
    stan = {"otwarte": False}
    kontener_akcji = ft.Column(spacing=10, horizontal_alignment=ft.CrossAxisAlignment.END, visible=False)

    fab_glowny = ft.FloatingActionButton(
        icon=ikona_glowna, bgcolor=ft.Colors.PRIMARY, foreground_color=ft.Colors.ON_PRIMARY, tooltip=tooltip,
    )

    def odswiez():
        kontener_akcji.visible = stan["otwarte"]
        fab_glowny.icon = ft.Icons.CLOSE if stan["otwarte"] else ikona_glowna
        fab_glowny.bgcolor = ft.Colors.ON_SURFACE_VARIANT if stan["otwarte"] else ft.Colors.PRIMARY
        try:
            page.update()
        except Exception:
            pass

    def zamknij():
        stan["otwarte"] = False
        odswiez()

    def przelacz(e):
        stan["otwarte"] = not stan["otwarte"]
        odswiez()

    fab_glowny.on_click = przelacz

    def opakuj_akcje(akcja):
        async def wrapper(e):
            zamknij()
            wynik = akcja(e)
            if asyncio.iscoroutine(wynik):
                await wynik
        return wrapper

    wiersze = []
    for ikona, etykieta, akcja in akcje:
        wiersze.append(
            ft.Row([
                ft.Container(
                    padding=ft.Padding(10, 6, 10, 6), border_radius=8,
                    bgcolor=ft.Colors.SURFACE,
                    shadow=ft.BoxShadow(blur_radius=4, color=ft.Colors.with_opacity(0.25, ft.Colors.BLACK)),
                    content=ft.Text(etykieta, size=12, weight="bold")
                ),
                ft.FloatingActionButton(
                    icon=ikona, mini=True, bgcolor=ft.Colors.SURFACE, foreground_color=ft.Colors.PRIMARY,
                    on_click=opakuj_akcje(akcja)
                )
            ], alignment=ft.MainAxisAlignment.END, vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=10)
        )

    kontener_akcji.controls = wiersze
    return ft.Column([kontener_akcji, fab_glowny], horizontal_alignment=ft.CrossAxisAlignment.END, spacing=10, tight=True)

def fab_animowany(icon, on_click, tooltip=None):
    """FloatingActionButton z 'namacalnym' feedbackiem dotyku — lekkie
    zmniejszenie (scale) przy naciśnięciu i płynny powrót."""
    fab = ft.FloatingActionButton(
        icon=icon, bgcolor=ft.Colors.PRIMARY, foreground_color=ft.Colors.ON_PRIMARY,
        tooltip=tooltip, scale=1.0,
        animate_scale=ft.Animation(120, ft.AnimationCurve.EASE_OUT),
    )

    async def _obsluz_klik(e):
        fab.scale = 0.88
        fab.update()
        await asyncio.sleep(0.09)
        fab.scale = 1.0
        fab.update()
        if on_click:
            wynik = on_click(e)
            if asyncio.iscoroutine(wynik):
                await wynik

    fab.on_click = _obsluz_klik
    return fab

class ZaznaczanieGrupowe:
    """Mixin: obsługa zaznaczania wielu kart + appbar trybu zaznaczania.
    Klasa używająca mixinu musi ustawić self.oryginalny_appbar i self.karty_ref
    oraz zaimplementować własne potwierdz_grupowe_usuwanie (bo logika usuwania
    i ewentualne przeliczenia różnią się w zależności od widoku)."""

    def dostosuj_wysokosc_listy(self):
        """Metoda wywoływana przy zdarzeniu on_resized ekranu.
        Dynamicznie przelicza wysokość dla wszystkich list wirtualizowanych w widoku."""
        if not getattr(self, "uzyj_wirtualizacji", False):
            return
            
        try:
            # Flet View ma domyślnie właściwość .page, ale wspieramy też Twoje self._page
            strona = getattr(self, "page", None) or getattr(self, "_page", None)
            if not strona: return
            
            nowa_wysokosc = wysokosc_listy(strona)
            
            # Magia Pythona: dynamicznie szukamy atrybutów, które nazwałeś jako 'lista_kart...'
            for nazwa_atrybutu in dir(self):
                if nazwa_atrybutu.startswith("lista_kart"):
                    lista = getattr(self, nazwa_atrybutu)
                    if hasattr(lista, "height") and lista.height != nowa_wysokosc:
                        lista.height = nowa_wysokosc
                        lista.update()
        except Exception:
            pass

    def zakoncz_zaznaczanie(self, e=None):
        self.tryb_zaznaczania = False
        self.zaznaczone_id.clear()
        self.appbar = self.oryginalny_appbar
        for kontener in self.karty_ref.values():
            kontener.bgcolor = None
            kontener.border = None
        self.update()

    def aktualizuj_appbar_zaznaczania(self, dodatkowe_akcje=None):
        akcje = list(dodatkowe_akcje or [])
        akcje.append(ft.IconButton(ft.Icons.DELETE, icon_color=ft.Colors.RED_700, tooltip="Usuń zaznaczone", on_click=self.potwierdz_grupowe_usuwanie))
        akcje.append(ft.Container(width=10))
        self.appbar = ft.AppBar(
            leading=ft.IconButton(ft.Icons.CLOSE, on_click=self.zakoncz_zaznaczanie),
            title=ft.Text(f"Zaznaczono: {len(self.zaznaczone_id)}", weight="bold"),
            bgcolor=ft.Colors.with_opacity(0.2, ft.Colors.PRIMARY),
            actions=akcje
        )
        self.update()

    def zaznacz_odznacz(self, element_id, kontener):
        if element_id in self.zaznaczone_id:
            self.zaznaczone_id.remove(element_id)
            kontener.bgcolor = None
            kontener.border = None
        else:
            self.zaznaczone_id.add(element_id)
            kontener.bgcolor = ft.Colors.with_opacity(0.15, ft.Colors.PRIMARY)
            kontener.border = ft.Border.all(2, ft.Colors.PRIMARY)

        if not self.zaznaczone_id:
            self.zakoncz_zaznaczanie()
        else:
            self.aktualizuj_appbar_zaznaczania()

    def podepnij_zdarzenia_grupowe(self, kontener, element_id, callback_pojedynczy, tabela=None):
        def _on_click(e):
            if self.tryb_zaznaczania:
                if tabela is None or getattr(self, "tabela_cel", tabela) == tabela:
                    self.zaznacz_odznacz(element_id, kontener)
            else:
                callback_pojedynczy()

        def _on_long_press(e):
            if not self.tryb_zaznaczania:
                self.tryb_zaznaczania = True
                if tabela is not None:
                    self.tabela_cel = tabela
                self.zaznacz_odznacz(element_id, kontener)

        kontener.on_click = _on_click
        kontener.on_long_press = _on_long_press