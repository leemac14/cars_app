"""Komunikaty, dialogi, arkusze dolne, menu i przejścia między ekranami."""

import asyncio
import flet as ft

from .stale import FS, RADIUS
from .wyglad import dol_bezpieczny
from .zgodnosc import ustaw_ikone


def pokaz_komunikat(page: ft.Page, wiadomosc, kolor=ft.Colors.GREEN_700):
    snack = ft.SnackBar(ft.Text(str(wiadomosc)), bgcolor=kolor)
    if hasattr(page, "open"):
        page.open(snack)
    else:
        page.overlay.append(snack)
        snack.open = True
        page.update()


def pokaz_komunikat_cofnij(page: ft.Page, wiadomosc, wynik_usuwania, sekundy=5, wiadomosc_bledu=None):
    """wynik_usuwania to słownik zwrócony przez db.usun_z_cofnieciem().

    None znaczy, że nic nie zostało usunięte — bo rekordu już nie ma albo bo
    rola przy tym pojeździe na to nie pozwala (patrz db/usuwanie._wolno_usunac).
    Wypisywanie wtedy „Pomyślnie usunięto...” na czerwono mówiło coś dokładnie
    odwrotnego do tego, co się stało."""
    if not wynik_usuwania:
        return pokaz_komunikat(
            page,
            wiadomosc_bledu or "Nie usunięto: wpisu już nie ma albo nie masz do niego uprawnień.",
            ft.Colors.RED_700
        )

    pominiete = wynik_usuwania.get("pominiete") if isinstance(wynik_usuwania, dict) else 0
    if pominiete:
        wiadomosc = f"{wiadomosc} Pominięto {pominiete} cudzych wpisów."

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


def pokaz_menu_grupowane(page: ft.Page, tytul: str, grupy: list, podtytul: str | None = None):
    """Menu z pozycjami POGRUPOWANYMI w rozwijane sekcje (BottomSheet).

    Płaskie menu z kilkunastoma pozycjami zmusza do czytania wszystkiego, żeby
    znaleźć jedną rzecz — a przy okazji stawia obok siebie sąsiadów, którzy nic
    wspólnego nie mają (kalkulator trasy i dziennik pojazdu). Tu widać kilka
    nagłówków; szczegóły pokazują się dopiero po rozwinięciu sekcji.

    grupy: lista słowników
        {"tytul": str, "ikona": ikona Material, "otwarta": bool,
         "pozycje": [{"ikona", "tekst", "opis", "akcja", "kolor", "odznaka"}]}
    Grupa bez pozycji jest pomijana, więc wołający może budować listę warunkowo
    (np. sekcja współdzielenia tylko dla pojazdu udostępnionego).
    """
    bs = ft.BottomSheet(ft.Container(padding=ft.Padding(16, 16, 16, 8), bgcolor=ft.Colors.SURFACE))

    def opakuj_akcje(akcja_docelowa):
        async def wrapper(e):
            zamknij_dno(page, bs)
            if akcja_docelowa:
                wynik = akcja_docelowa()
                if asyncio.iscoroutine(wynik):
                    await wynik
        return wrapper

    def zbuduj_pozycje(poz):
        kolor = poz.get("kolor") or ft.Colors.ON_SURFACE
        opis = poz.get("opis")
        odznaka = poz.get("odznaka")

        tytul_wiersza = [ft.Text(poz.get("tekst", ""), size=FS["body"], color=kolor, weight="w500")]
        if odznaka:
            tytul_wiersza.append(ft.Container(
                padding=ft.Padding(7, 1, 7, 1),
                border_radius=RADIUS["pill"],
                bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.ORANGE_700),
                content=ft.Text(str(odznaka), size=10, weight="bold", color=ft.Colors.ORANGE_800),
            ))

        tresc = [ft.Row(tytul_wiersza, spacing=6, tight=True)]
        if opis:
            tresc.append(ft.Text(opis, size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT))

        return ft.Container(
            padding=ft.Padding(10, 10, 10, 10),
            border_radius=RADIUS["sm"],
            ink=True,
            on_click=opakuj_akcje(poz.get("akcja")),
            content=ft.Row([
                ft.Icon(poz.get("ikona"), size=20, color=poz.get("kolor") or ft.Colors.PRIMARY),
                ft.Column(tresc, spacing=1, tight=True, expand=True),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )

    sekcje = []
    for grupa in grupy:
        pozycje = [p for p in (grupa.get("pozycje") or []) if p]
        if not pozycje:
            continue

        cialo = ft.Container(
            padding=ft.Padding(0, 0, 0, 6),
            visible=bool(grupa.get("otwarta")),
            content=ft.Column([zbuduj_pozycje(p) for p in pozycje], spacing=2, tight=True),
        )
        strzalka = ft.Icon(
            ft.Icons.KEYBOARD_ARROW_UP if cialo.visible else ft.Icons.KEYBOARD_ARROW_DOWN,
            size=20, color=ft.Colors.ON_SURFACE_VARIANT,
        )

        def przelacz(e, cialo=cialo, strzalka=strzalka):
            cialo.visible = not cialo.visible
            ustaw_ikone(strzalka, ft.Icons.KEYBOARD_ARROW_UP if cialo.visible else ft.Icons.KEYBOARD_ARROW_DOWN)
            try:
                page.update()
            except Exception:
                pass

        naglowek = ft.Container(
            padding=ft.Padding(10, 12, 10, 12),
            border_radius=RADIUS["sm"],
            ink=True,
            on_click=przelacz,
            content=ft.Row([
                ft.Icon(grupa.get("ikona"), size=20, color=ft.Colors.PRIMARY),
                ft.Text(grupa.get("tytul", ""), size=FS["body"], weight="bold", expand=True),
                ft.Text(str(len(pozycje)), size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT),
                strzalka,
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )
        sekcje.append(ft.Column([naglowek, cialo], spacing=0, tight=True))

    naglowek_menu = [ft.Text(tytul, weight="bold", size=18, color=ft.Colors.PRIMARY)]
    if podtytul:
        naglowek_menu.append(ft.Text(podtytul, size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT))

    bs.content.content = ft.Column(
        [ft.Column(naglowek_menu, spacing=0, tight=True), ft.Divider(height=12)] + sekcje,
        tight=True, spacing=0,
    )
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


__all__ = [
    "otworz_dialog",
    "otworz_dno",
    "pokaz_komunikat",
    "pokaz_komunikat_cofnij",
    "pokaz_ladowanie",
    "pokaz_menu_grupowane",
    "pokaz_menu_kontekstowe",
    "potwierdz",
    "przejdz",
    "ukryj_ladowanie",
    "z_opoznieniem",
    "zamknij_dialog",
    "zamknij_dno",
]
