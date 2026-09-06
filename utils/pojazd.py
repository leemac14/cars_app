"""Elementy związane z pojazdem: odznaka, tablica, terminy, kondycja."""

import db
import flet as ft

from .stale import FS, IKONY_NADWOZIA, KOLOR_STATUS, MAPA_KOLOROW, RADIUS, SPACING, ikona_z_mapy
from .wyglad import powierzchnia_karty
from .dialogi import otworz_dno, pokaz_komunikat_cofnij, potwierdz, przejdz, zamknij_dno
from .wykresy import kolor_kondycji_plynny


def usun_auto(page: ft.Page, state):
    if not state.auto_id: return
    nazwa = state.auto_nazwa
    auto_id = state.auto_id

    def wykonaj():
        # Pojazd trafia do kosza — nic nie jest kasowane z dysku.
        wynik = db.usun_auto_do_kosza(auto_id)

        if wynik:
            oryg_cofnij = wynik["cofnij"]
            def nowe_cofnij():
                oryg_cofnij()
                # Przywrócenie mogło nadać pojazdowi nowe ID (gdyby stare zdążył
                # zająć inny wpis), więc bierzemy to, które faktycznie wróciło.
                nowe_id = wynik.get("przywrocone_id")
                if nowe_id:
                    state.auto_id = nowe_id
                    db.zainicjuj_domyslne_auto(state)
                przejdz(page, "/")
            wynik["cofnij"] = nowe_cofnij

        state.auto_id = None
        db.zainicjuj_domyslne_auto(state)
        przejdz(page, "/")
        pokaz_komunikat_cofnij(page, f"Pojazd „{nazwa}” przeniesiony do kosza.", wynik)

    dni = db.pobierz_dni_kosza()
    okres = f"przez {dni} dni" if dni else "bez limitu czasu"
    potwierdz(
        page, "Usunąć pojazd?",
        f"„{nazwa}” trafi do kosza wraz z całą historią serwisową i zdjęciami. "
        f"Będzie tam czekał {okres} — do tego czasu przywrócisz go jednym kliknięciem.",
        wykonaj,
        tekst_potwierdzenia="Przenieś do kosza",
    )


def ikona_nadwozia(nadwozie):
    return ikona_z_mapy(IKONY_NADWOZIA, nadwozie, ft.Icons.DIRECTIONS_CAR)


def odznaka_pojazdu(auto, rozmiar=40, kolor_nazwa=None):
    """Krążek z sylwetką nadwozia w kolorze przypisanym do TEGO pojazdu.

    Do tej pory każde auto w selektorze wyglądało identycznie i rozróżniało się
    je dopiero po przeczytaniu nazwy. Sylwetka plus własny kolor dają rozpoznanie
    jednym spojrzeniem, a gdy typ nadwozia nie jest uzupełniony, zostaje ogólna
    ikona samochodu — czyli dokładnie to, co było.

    `auto` to wiersz/słownik z kolumnami 'nadwozie' i (opcjonalnie) 'kolor_motywu'.
    """
    def pole(nazwa):
        try:
            return auto[nazwa]
        except Exception:
            return None

    nadwozie = pole("nadwozie")
    kolor = MAPA_KOLOROW.get(kolor_nazwa or pole("kolor_motywu") or "", None)
    if kolor is None:
        kolor = ft.Colors.PRIMARY

    return ft.Container(
        width=rozmiar, height=rozmiar, border_radius=rozmiar // 2,
        bgcolor=ft.Colors.with_opacity(0.16, kolor),
        border=ft.Border.all(2, ft.Colors.with_opacity(0.45, kolor)),
        alignment=ft.Alignment.CENTER,
        tooltip=str(nadwozie) if nadwozie else None,
        content=ft.Icon(ikona_nadwozia(nadwozie), size=int(rozmiar * 0.5), color=kolor),
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


def pokaz_panel_kondycji(page: ft.Page, state):
    """Rozpiska tego, co obniża kondycję pojazdu. Sam wynik 0-100 nie mówi, CO
    poprawić — tu każdy minus ma powód, liczbę punktów i prowadzi tam, gdzie da
    się z nim coś zrobić."""
    rozbicie = db.pobierz_rozbicie_kondycji(state.auto_id)
    wynik = rozbicie["wynik"]
    powody = rozbicie["powody"]
    kolor, ikona, etykieta = wskaznik_kondycji(wynik)

    bs = ft.BottomSheet(ft.Container(padding=ft.Padding(16, 16, 16, 8), bgcolor=ft.Colors.SURFACE))

    def idz_do(trasa):
        def handler(e):
            zamknij_dno(page, bs)
            przejdz(page, trasa)
        return handler

    naglowek = ft.Row([
        ft.Icon(ikona, size=26, color=kolor),
        ft.Column([
            ft.Text("Kondycja pojazdu", weight="bold", size=18, color=ft.Colors.PRIMARY),
            ft.Text(f"{wynik if wynik is not None else '-'}/100 · {etykieta}",
                    size=FS["label"], weight="bold", color=kolor),
        ], spacing=0, tight=True, expand=True),
    ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    # Pasek wyniku: 100 punktów startowych, z których odjęto to, co niżej.
    pasek = ft.Container(
        height=8, border_radius=RADIUS["pill"],
        bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
        content=ft.Row([
            ft.Container(
                expand=max(1, wynik or 0), height=8,
                border_radius=RADIUS["pill"],
                bgcolor=kolor_kondycji_plynny(wynik) if wynik is not None else ft.Colors.ON_SURFACE_VARIANT,
            ),
            ft.Container(expand=max(1, 100 - (wynik or 0))),
        ], spacing=0),
    )

    zawartosc = [naglowek, ft.Container(height=4), pasek, ft.Divider(height=14)]

    if not powody:
        zawartosc.append(ft.Container(
            padding=ft.Padding(12, 18, 12, 18),
            alignment=ft.Alignment.CENTER,
            content=ft.Column([
                ft.Icon(ft.Icons.TASK_ALT, size=40, color=KOLOR_STATUS["ok"]),
                ft.Text("Nic nie obniża kondycji", weight="bold"),
                ft.Text("Żaden podzespół nie jest przeterminowany, a bieżnik zamontowanych "
                        "opon mieści się w normie.",
                        size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                        text_align=ft.TextAlign.CENTER),
            ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        ))
    else:
        suma = sum(p["punkty"] for p in powody)
        zawartosc.append(ft.Text(
            f"Odjęto łącznie {suma} pkt · {len(powody)} "
            + ("powód" if len(powody) == 1 else "powody" if len(powody) < 5 else "powodów"),
            size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
        ))

        IKONY_POWODU = {"podzespol": ft.Icons.HANDYMAN, "opony": ft.Icons.TIRE_REPAIR}
        for p in powody:
            # Największe minusy pierwsze (sortuje db), więc czerwień u góry to
            # jednocześnie „zajmij się tym najpierw”.
            kolor_kary = ft.Colors.RED_700 if p["punkty"] >= 15 else ft.Colors.ORANGE_800
            tresc = [ft.Text(p["opis"], size=FS["label"], weight="bold")]
            if p["szczegol"]:
                tresc.append(ft.Text(p["szczegol"], size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT))

            powierzchnia = powierzchnia_karty(page, "sm")
            zawartosc.append(ft.Container(
                padding=ft.Padding(12, 12, 12, 12),
                border_radius=RADIUS["md"],
                bgcolor=powierzchnia["bgcolor"],
                border=powierzchnia["border"],
                ink=bool(p["trasa"]),
                on_click=idz_do(p["trasa"]) if p["trasa"] else None,
                content=ft.Row([
                    ft.Container(
                        padding=ft.Padding(8, 4, 8, 4),
                        border_radius=RADIUS["sm"],
                        bgcolor=ft.Colors.with_opacity(0.14, kolor_kary),
                        content=ft.Text(f"−{p['punkty']} pkt", size=FS["caption"],
                                        weight="bold", color=kolor_kary),
                    ),
                    ft.Icon(ikona_z_mapy(IKONY_POWODU, p["typ"], ft.Icons.WARNING_AMBER),
                            size=18, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Column(tresc, spacing=1, tight=True, expand=True),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, size=18,
                            color=ft.Colors.ON_SURFACE_VARIANT, visible=bool(p["trasa"])),
                ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ))

        zawartosc.append(ft.Text(
            "Kondycja liczy tylko stan techniczny: podzespoły z przekroczonym interwałem "
            "i bieżnik zamontowanych opon. Dokumenty, magazyn i wydatki cykliczne jej nie ruszają.",
            size=FS["caption"], italic=True, color=ft.Colors.ON_SURFACE_VARIANT,
        ))

    bs.content.content = ft.Column(zawartosc, tight=True, spacing=8)
    otworz_dno(page, bs)


# ==================== ANALIZA: WSPÓLNE KOMPONENTY ====================
# Kokpit, zakładka Analiza i ekran budżetów rysują te same rzeczy — jedna
# definicja na komponent, żeby ostrzeżenie o budżecie wyglądało wszędzie tak
# samo i żeby zmiana progu nie wymagała szukania po trzech plikach.

# ==================== TOŻSAMOŚĆ POJAZDU ====================

def tablica_rejestracyjna(nr_rej, wysokosc=30, on_click=None):
    """Numer rejestracyjny narysowany jak prawdziwa tablica: niebieski pasek UE
    z „PL” po lewej, czarny tekst na białym tle, ciemna ramka.

    To nie jest ozdobnik bez funkcji. Rejestracja jest tym, po czym rozpoznaje
    się auto w realnym świecie (parking, ubezpieczyciel, warsztat), a jako szary
    tekst obok innych szarych tekstów po prostu ginęła. W tej formie znajduje ją
    oko, zanim zacznie czytać."""
    numer = " ".join(str(nr_rej or "").split()).upper()
    if not numer:
        return ft.Container(width=0, height=0)

    return ft.Container(
        height=wysokosc,
        border_radius=RADIUS["xs"],
        bgcolor="#FFFFFF",
        border=ft.Border.all(1.5, "#1F2937"),
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        ink=bool(on_click), on_click=on_click,
        tooltip="Numer rejestracyjny" if not on_click else "Dotknij, aby skopiować",
        content=ft.Row([
            ft.Container(
                # Wysokość podana WPROST: w Row dziecko bez własnej wysokości
                # kurczy się do treści i niebieski pasek nie sięgałby krawędzi.
                width=wysokosc * 0.52, height=wysokosc, bgcolor="#003399",
                alignment=ft.Alignment.CENTER,
                content=ft.Column([
                    ft.Text("★", size=wysokosc * 0.22, color="#FFCC00"),
                    ft.Text("PL", size=wysokosc * 0.30, weight="bold", color="#FFFFFF"),
                ], spacing=0, alignment=ft.MainAxisAlignment.CENTER,
                   horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            ),
            ft.Container(
                height=wysokosc,
                padding=ft.Padding(wysokosc * 0.30, 0, wysokosc * 0.30, 0),
                alignment=ft.Alignment.CENTER,
                content=ft.Text(numer, size=wysokosc * 0.50, weight="bold", color="#111827",
                                no_wrap=True),
            ),
        ], spacing=0, tight=True),
    )


KOLORY_STATUSU_TERMINU = {
    "po_terminie": ft.Colors.RED_700,
    "blisko": ft.Colors.ORANGE_700,
    "ok": ft.Colors.GREEN_700,
}


IKONY_STATUSU_TERMINU = {
    "po_terminie": ft.Icons.WARNING,
    "blisko": ft.Icons.HOURGLASS_BOTTOM,
    "ok": ft.Icons.CHECK_CIRCLE,
}


IKONY_TERMINOW = {
    "oc": ft.Icons.SHIELD,
    "przeglad": ft.Icons.FACT_CHECK,
    "ac": ft.Icons.HEALTH_AND_SAFETY,
    "assistance": ft.Icons.SUPPORT_AGENT,
    "gwarancja": ft.Icons.VERIFIED_USER,
    "gasnica": ft.Icons.LOCAL_FIRE_DEPARTMENT,
    "apteczka": ft.Icons.MEDICAL_SERVICES,
}


def opis_dni_terminu(dni):
    """„za 12 dni” / „dzisiaj” / „5 dni po terminie” — jedno miejsce na tę
    odmianę, bo pojawia się i na kaflu, i na ekranie danych pojazdu."""
    if dni is None:
        return ""
    if dni < 0:
        ile = abs(dni)
        return f"{ile} {'dzień' if ile == 1 else 'dni'} po terminie"
    if dni == 0:
        return "dzisiaj"
    if dni == 1:
        return "jutro"
    return f"za {dni} dni"


def pasek_terminu(page: ft.Page, termin, pelny=True):
    """Wiersz terminu dokumentu z odliczaniem i paskiem. Pasek pokazuje, ile
    z okna ostrzegawczego już minęło — wypełnia się dopiero, gdy termin wchodzi
    w próg powiadomienia, więc „zielony i pusty” znaczy „jeszcze długo”."""
    kolor = KOLORY_STATUSU_TERMINU.get(termin["status"], ft.Colors.ON_SURFACE_VARIANT)
    prog = max(1, termin.get("prog") or 30)
    if termin["dni"] < 0:
        udzial = 1.0
    else:
        udzial = max(0.0, min(1.0, 1 - (termin["dni"] / prog))) if termin["dni"] <= prog else 0.0

    gorny = ft.Row([
        ft.Icon(ikona_z_mapy(IKONY_TERMINOW, termin["klucz"], ft.Icons.EVENT), size=16, color=kolor),
        ft.Text(termin["etykieta"], size=FS["body_strong"], weight="bold", expand=True,
                no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
        ft.Text(termin["data"], size=FS["body"], weight="bold", color=kolor),
    ], spacing=6)

    elementy = [gorny]
    if pelny:
        elementy.append(ft.ProgressBar(
            value=udzial, color=kolor,
            bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
            height=6, border_radius=3,
        ))
        elementy.append(ft.Row([
            ft.Icon(ikona_z_mapy(IKONY_STATUSU_TERMINU, termin["status"], ft.Icons.EVENT),
                    size=12, color=kolor),
            ft.Text(opis_dni_terminu(termin["dni"]), size=FS["caption"], color=kolor, expand=True),
        ], spacing=4))

    return ft.Column(elementy, spacing=SPACING["xs"])


__all__ = [
    "IKONY_STATUSU_TERMINU",
    "IKONY_TERMINOW",
    "KOLORY_STATUSU_TERMINU",
    "ikona_nadwozia",
    "odznaka_pojazdu",
    "opis_dni_terminu",
    "pasek_terminu",
    "pokaz_panel_kondycji",
    "tablica_rejestracyjna",
    "usun_auto",
    "wskaznik_kondycji",
]
