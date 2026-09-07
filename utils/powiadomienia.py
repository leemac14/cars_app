"""Dzwonek, panel przypomnień i panel wydatków cyklicznych."""

import db
import flet as ft
from datetime import datetime

from .stale import IKONY_SEZONU_OPON, KOLOR_STATUS, RADIUS, formatuj_liczba
from .format import kolor_i_tekst_terminu, parsuj_float, parsuj_int, symbol_waluty
from .zgodnosc import ustaw_blad, ustaw_ikone
from .wyglad import dol_bezpieczny
from .dialogi import otworz_dialog, otworz_dno, pokaz_komunikat, potwierdz, przejdz, zamknij_dialog, zamknij_dno
from .formularze import pole_daty, styl_dropdown, styl_pola
from .komponenty import znacznik_wykonania


def _sygnatura_powiadomien(powiadomienia):
    return frozenset((p["typ"], p["tytul"], p["status"]) for p in powiadomienia)


# Wpis typu „opony” nie jest ani płatnością, ani gołym przypomnieniem — jego
# odhaczenie przestawia zamontowany komplet, więc i przycisk, i komunikat muszą
# mówić o czymś innym niż „Zapłacone”.
def etykieta_wykonania_cyklicznego(typ, czy_koszt):
    if typ == db.TYP_CYKLICZNY_OPONY:
        return "Zmieniono"
    return "Zapłacone" if czy_koszt else "Wykonano"


def ikona_wpisu_cyklicznego(typ, czy_koszt):
    if typ == db.TYP_CYKLICZNY_OPONY:
        return ft.Icons.TIRE_REPAIR
    return ft.Icons.AUTORENEW if czy_koszt else ft.Icons.NOTIFICATIONS_ACTIVE


def komunikat_zmiany_opon(opony):
    """Zdanie opisujące, co się stało z kompletem opon. Osobno od reszty, bo tę
    samą informację pokazuje panel przypomnień i ekran Magazyn → Opony."""
    opony = opony or {}
    if opony.get("ok"):
        skad = f" (zdjęto: {opony['z'].lower()})" if opony.get("z") else ""
        opis = f" — {opony['opis_zestawu']}" if opony.get("opis_zestawu") else ""
        return f"Zamontowano opony {str(opony.get('na') or '').lower()}{opis}{skad}."
    if opony.get("powod") == "brak_zestawow":
        return "W magazynie nie ma żadnego zestawu opon do zamontowania."
    docelowy = str(opony.get("docelowy_sezon") or "").lower()
    return f"Nie zmieniono opon — brak wolnego zestawu ({docelowy}) w magazynie."


def komunikat_po_wykonaniu(wynik, czy_koszt=True):
    """Zdanie, które użytkownik zobaczy po odhaczeniu wpisu cyklicznego.

    Przy sezonowej zmianie opon musi powiedzieć, CO SIĘ STAŁO Z DANYMI: albo
    „zamontowano zimowe”, albo — jeśli drugiego kompletu nie ma w magazynie —
    że termin przesunięto, ale opon nie zmieniono. Cicha zmiana albo ciche jej
    pominięcie byłyby tu równie złe."""
    if not isinstance(wynik, dict):
        return "Zapisano płatność i przesunięto termin." if czy_koszt else "Oznaczono jako wykonane i przesunięto termin."

    czy_koszt = wynik.get("czy_koszt", czy_koszt)
    if wynik.get("typ") != db.TYP_CYKLICZNY_OPONY:
        return "Zapisano płatność i przesunięto termin." if czy_koszt else "Oznaczono jako wykonane i przesunięto termin."

    opony = wynik.get("opony") or {}
    if opony.get("ok"):
        return komunikat_zmiany_opon(opony)
    return "Przesunięto termin. " + komunikat_zmiany_opon(opony)


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
    # Jak w panelu wydatków: podmieniamy TREŚĆ stałej kolumny, a nie cały
    # `bs.content` — inaczej odłożenie albo odhaczenie powiadomienia nie było
    # widać w już otwartym arkuszu.
    lista_pozycji = ft.Column([], tight=True, spacing=4, scroll=ft.ScrollMode.AUTO)
    bs = ft.BottomSheet(ft.Container(
        padding=20, bgcolor=ft.Colors.SURFACE, content=lista_pozycji,
    ))

    def idz_do(trasa):
        def handler(e):
            zamknij_dno(page, bs)
            przejdz(page, trasa)
        return handler

    def zaplac_cykliczny(wydatek_id, czy_koszt=True, kafelek=None, typ=None):
        def handler(e):
            wynik = db.oznacz_zaplacony_wydatek_cykliczny(wydatek_id, state.auto_id)
            komunikat = komunikat_po_wykonaniu(wynik, czy_koszt)

            def dokoncz():
                pokaz_komunikat(page, komunikat)
                przejdz(page, page.route)  # odświeża dzwonek/badge w tle; panel zostaje otwarty
                odswiez()

            if kafelek is None:
                dokoncz()
                return

            # Przycisk zamienia się w ptaszka, który „wskakuje” na swoje miejsce,
            # i dopiero po tej chwili lista się przebudowuje — inaczej wiersz
            # znikał w tej samej klatce, w której użytkownik go dotknął.
            kafelek.trailing = znacznik_wykonania(
                page,
                etykieta_wykonania_cyklicznego(typ, czy_koszt),
                po_zakonczeniu=dokoncz,
            )
            try:
                page.update()
            except Exception:
                pass
        return handler

    def odloz(powiadomienie, dni):
        """Wycisza JEDNO powiadomienie na wybraną liczbę dni. Nie oznacza niczego
        jako wykonane i nie rusza terminu — po prostu znika z listy do czasu."""
        db.odloz_powiadomienie(state.auto_id, powiadomienie.get("klucz"), dni, powiadomienie.get("tytul"))
        pokaz_komunikat(page, f"Odłożono „{powiadomienie['tytul']}” na {dni} dni.")
        przejdz(page, page.route)   # odświeża licznik przy dzwonku w tle
        odswiez()

    def okno_wlasnej_liczby_dni(powiadomienie):
        e_dni = ft.TextField(label="Za ile dni przypomnieć?", value="14",
                             keyboard_type=ft.KeyboardType.NUMBER, **styl_pola())

        def zapisz(e):
            dni = parsuj_int(e_dni.value, 0)
            if dni < 1:
                ustaw_blad(e_dni, "Podaj liczbę dni (min. 1)")
                e_dni.update()
                return
            zamknij_dialog(page, dlg)
            odloz(powiadomienie, dni)

        dlg = ft.AlertDialog(
            title=ft.Text("Odłóż przypomnienie", weight="bold"),
            content=ft.Column([
                ft.Text(powiadomienie["tytul"], weight="bold"),
                ft.Text("Wróci na listę po tylu dniach. Termin i status pozostają bez zmian.",
                        size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                e_dni,
            ], tight=True, spacing=10),
            actions=[
                ft.TextButton("Anuluj", on_click=lambda e: zamknij_dialog(page, dlg)),
                ft.ElevatedButton("Odłóż", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY),
            ],
        )
        otworz_dialog(page, dlg)

    def przycisk_odlozenia(powiadomienie):
        if not powiadomienie.get("klucz"):
            return None
        pozycje_menu = [
            ft.PopupMenuItem(
                content=ft.Row([ft.Icon(ft.Icons.SNOOZE, size=16, color=ft.Colors.PRIMARY),
                                ft.Text(f"Za {d} dni")], spacing=6),
                on_click=lambda e, dni=d, p=powiadomienie: odloz(p, dni),
            )
            for d in db.DNI_ODLOZENIA_OPCJE
        ]
        pozycje_menu.append(ft.PopupMenuItem(
            content=ft.Row([ft.Icon(ft.Icons.EDIT_CALENDAR, size=16, color=ft.Colors.PRIMARY),
                            ft.Text("Własna liczba dni")], spacing=6),
            on_click=lambda e, p=powiadomienie: okno_wlasnej_liczby_dni(p),
        ))
        return ft.PopupMenuButton(
            items=pozycje_menu,
            tooltip="Odłóż to przypomnienie",
            content=ft.Container(
                width=36, height=36, alignment=ft.Alignment.CENTER,
                content=ft.Icon(ft.Icons.SNOOZE, size=18, color=ft.Colors.ON_SURFACE_VARIANT),
            ),
        )

    def sekcja_odlozonych():
        odlozone = db.pobierz_odlozone_powiadomienia(state.auto_id)
        if not odlozone:
            return []

        wiersze = ft.Column([], spacing=0, tight=True, visible=False)
        strzalka = ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN, size=20, color=ft.Colors.ON_SURFACE_VARIANT)

        for o in odlozone:
            podtytul = f"Wróci {o['data_tekst']}"
            if o["dni_do_powrotu"] == 0:
                podtytul = "Wróci jutro"
            elif o["dni_do_powrotu"] == 1:
                podtytul = "Wróci za 1 dzień"
            elif o["dni_do_powrotu"] > 1:
                podtytul = f"Wróci za {o['dni_do_powrotu']} dni ({o['data_tekst']})"
            if not o["nadal_aktualne"]:
                podtytul += " • powód już nieaktualny"

            wiersze.controls.append(ft.ListTile(
                leading=ft.Icon(ft.Icons.SNOOZE, color=ft.Colors.ON_SURFACE_VARIANT),
                title=ft.Text(o["tytul"], color=ft.Colors.ON_SURFACE_VARIANT),
                subtitle=ft.Text(podtytul, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                trailing=ft.TextButton(
                    "Przywróć",
                    on_click=lambda e, k=o["klucz"]: (
                        db.przywroc_powiadomienie(state.auto_id, k),
                        przejdz(page, page.route),
                        odswiez(),
                    ),
                ),
            ))

        def przelacz(e):
            wiersze.visible = not wiersze.visible
            ustaw_ikone(strzalka, ft.Icons.KEYBOARD_ARROW_UP if wiersze.visible else ft.Icons.KEYBOARD_ARROW_DOWN)
            try:
                page.update()
            except Exception:
                pass

        naglowek = ft.Container(
            padding=ft.Padding(12, 10, 12, 10),
            border_radius=RADIUS["sm"],
            ink=True, on_click=przelacz,
            content=ft.Row([
                ft.Icon(ft.Icons.SNOOZE, size=18, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(f"Odkładane ({len(odlozone)})", weight="bold",
                        color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                strzalka,
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )
        return [ft.Divider(height=8), naglowek, wiersze]

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
                content=ft.Row([
                    ft.Icon(ft.Icons.TASK_ALT, size=18, color=KOLOR_STATUS["ok"]),
                    ft.Text("Brak zbliżających się terminów", italic=True, color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                ], spacing=8)
            ))
        else:
            for p in powiadomienia:
                kolor = ft.Colors.RED_700 if p["status"] == "przeterminowane" else ft.Colors.ORANGE_700
                ikona = ft.Icons.WARNING if p["status"] == "przeterminowane" else ft.Icons.HOURGLASS_BOTTOM
                if p["typ"] == "cykliczny":
                    czy_koszt_p = p.get("czy_koszt", True)
                    typ_p = p.get("typ_cykliczny", db.TYP_CYKLICZNY_WYDATEK)
                    # Sezonowa zmiana opon dostaje własną ikonę zamiast klepsydry:
                    # na liście przypomnień ma się od razu odróżniać od rat i polis.
                    ikona_p = ft.Icons.TIRE_REPAIR if typ_p == db.TYP_CYKLICZNY_OPONY else ikona
                    kafelek = ft.ListTile(
                        leading=ft.Icon(ikona_p, color=kolor),
                        title=ft.Text(p["tytul"], weight="bold"),
                        subtitle=ft.Text(p["opis"], color=kolor, size=13),
                    )
                    akcje = [ft.TextButton(
                        etykieta_wykonania_cyklicznego(typ_p, czy_koszt_p),
                        icon=ft.Icons.CHECK,
                        on_click=zaplac_cykliczny(p["wydatek_id"], czy_koszt_p, kafelek, typ_p),
                    )]
                    drzemka = przycisk_odlozenia(p)
                    if drzemka:
                        akcje.append(drzemka)
                    kafelek.trailing = ft.Row(akcje, spacing=0, tight=True)
                    pozycje.append(kafelek)
                else:
                    pozycje.append(ft.ListTile(
                        leading=ft.Icon(ikona, color=kolor),
                        title=ft.Text(p["tytul"], weight="bold"),
                        subtitle=ft.Text(p["opis"], color=kolor, size=13),
                        trailing=przycisk_odlozenia(p),
                        on_click=idz_do(p["trasa"]),
                    ))

        # Odłożone trzymamy w zwijanej sekcji na dole: nie zaśmiecają listy,
        # ale nie znikają bez śladu — widać datę powrotu i można ją cofnąć.
        pozycje.extend(sekcja_odlozonych())

        pozycje.append(dol_bezpieczny(20))
        lista_pozycji.controls = pozycje
        try:
            lista_pozycji.update()
        except Exception:
            try:
                page.update()
            except Exception:
                pass

    odswiez()
    otworz_dno(page, bs)


def pokaz_panel_wydatkow_cyklicznych(page: ft.Page, state):
    """Lekki panel (BottomSheet) do zarządzania wydatkami cyklicznymi pojazdu
    (raty, abonamenty, ubezpieczenia ratalne) ORAZ zwykłymi przypomnieniami
    cyklicznymi bez kosztu (np. "co miesiąc sprawdź ciśnienie w oponach") —
    bez osobnej trasy, analogicznie do pokaz_panel_powiadomien()."""
    # Stała kolumna, której podmieniamy tylko `controls`. Podmiana całego
    # `bs.content` po każdej zmianie nie trafiała do już otwartego arkusza —
    # świeżo dodany wpis (np. sezonowa zmiana opon) pojawiał się dopiero po
    # zamknięciu i ponownym otwarciu panelu.
    lista_pozycji = ft.Column([], tight=True, spacing=4, scroll=ft.ScrollMode.AUTO)
    bs = ft.BottomSheet(ft.Container(
        padding=20, bgcolor=ft.Colors.SURFACE, content=lista_pozycji,
    ))

    def odswiez():
        wpisy = db.pobierz_wydatki_cykliczne(state.auto_id)
        pozycje = [
            ft.Row([
                ft.Icon(ft.Icons.AUTORENEW, color=ft.Colors.PRIMARY),
                ft.Text("Wydatki cykliczne i przypomnienia", weight="bold", size=18, color=ft.Colors.PRIMARY, expand=True)
            ], spacing=8),
            ft.Divider(height=1),
        ]

        if not wpisy:
            pozycje.append(ft.Container(
                padding=ft.Padding.symmetric(vertical=15),
                content=ft.Text("Brak zapisanych wydatków cyklicznych ani przypomnień.", italic=True, color=ft.Colors.ON_SURFACE_VARIANT)
            ))
        else:
            for w_id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt, typ in wpisy:
                kolor, tekst_daty = kolor_i_tekst_terminu(nastepna_data)
                czy_koszt = bool(czy_koszt)
                termin_txt = f"co {okres_dni} dni • {tekst_daty or nastepna_data}"
                if typ == db.TYP_CYKLICZNY_OPONY:
                    # Przy zmianie opon najważniejsze jest, CO stoi na aucie i co
                    # zostanie zamontowane — sam termin mówi tu najmniej.
                    stan = db.pobierz_stan_opon(state.auto_id) or {}
                    teraz = stan.get("sezon")
                    docelowy = stan.get("docelowy_sezon")
                    kierunek = f"{teraz} → {docelowy}" if teraz else (f"→ {docelowy}" if docelowy else "brak zestawów")
                    podtytul = f"Zmiana opon: {kierunek} • {termin_txt}"
                    if not stan.get("ma_para"):
                        podtytul += " • brak wolnego kompletu"
                elif czy_koszt:
                    podtytul = f"{formatuj_liczba(kwota)} {symbol_waluty()} • {termin_txt}"
                else:
                    podtytul = f"Przypomnienie • {termin_txt}"
                pozycje.append(ft.ListTile(
                    leading=ft.Icon(ikona_wpisu_cyklicznego(typ, czy_koszt), color=kolor),
                    title=ft.Text(str(nazwa), weight="bold"),
                    subtitle=ft.Text(podtytul, size=12, color=kolor),
                    trailing=ft.PopupMenuButton(items=[
                        ft.PopupMenuItem(
                            content=ft.Row([ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN, size=18),
                                            ft.Text(etykieta_wykonania_cyklicznego(typ, czy_koszt))]),
                            on_click=lambda e, wid=w_id, ck=czy_koszt: zaplac(wid, ck)
                        ),
                        ft.PopupMenuItem(
                            content=ft.Row([ft.Icon(ft.Icons.EDIT, size=18), ft.Text("Edytuj")]),
                            on_click=lambda e, w=(w_id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt, typ): formularz(w)
                        ),
                        ft.PopupMenuItem(
                            content=ft.Row([ft.Icon(ft.Icons.DELETE, color=ft.Colors.RED, size=18), ft.Text("Usuń")]),
                            on_click=lambda e, wid=w_id: usun(wid)
                        ),
                    ])
                ))

        pozycje.append(ft.Divider(height=1))
        pozycje.append(ft.TextButton("Dodaj wydatek / przypomnienie", icon=ft.Icons.ADD, on_click=lambda e: formularz(None)))
        if state.auto_id and not any(w[6] == db.TYP_CYKLICZNY_OPONY for w in wpisy):
            # Skrót zamiast pustego pola: sezonowa zmiana opon ma ten sam okres
            # i tę samą nazwę u każdego, więc nie ma czego wpisywać ręcznie.
            def dodaj_opony(e):
                db.dodaj_przypomnienie_o_oponach(state.auto_id)
                odswiez()
                pokaz_komunikat(page, "Dodano przypomnienie o sezonowej zmianie opon (co pół roku).")

            pozycje.append(ft.TextButton(
                "Dodaj sezonową zmianę opon", icon=ft.Icons.TIRE_REPAIR, on_click=dodaj_opony,
            ))

        # Margines na przyciski systemowe telefonu doklejamy SAMI: otworz_dno robi
        # to jednorazowo, a my podmieniamy zawartość kolumny przy każdym odświeżeniu.
        pozycje.append(dol_bezpieczny(20))
        lista_pozycji.controls = pozycje
        try:
            lista_pozycji.update()
        except Exception:
            # Kolumna nie jest jeszcze w drzewie strony (pierwsze budowanie
            # panelu) — otworz_dno pokaże ją już z aktualną treścią.
            try:
                page.update()
            except Exception:
                pass

    def zaplac(wydatek_id, czy_koszt=True):
        wynik = db.oznacz_zaplacony_wydatek_cykliczny(wydatek_id, state.auto_id)
        pokaz_komunikat(page, komunikat_po_wykonaniu(wynik, czy_koszt))
        odswiez()

    def usun(wydatek_id):
        def wykonaj():
            db.usun_wydatek_cykliczny(wydatek_id)
            odswiez()
            pokaz_komunikat(page, "Usunięto wpis.")
        potwierdz(page, "Usunąć?", "Czy na pewno usunąć ten wpis?", wykonaj)

    def formularz(istniejacy):
        edycja = istniejacy is not None
        w_id, nazwa_val, kwota_val, okres_val, data_val, czy_koszt_val, typ_val = (
            istniejacy if istniejacy is not None
            else (None, "", "", 30, datetime.now().strftime("%d.%m.%Y"), 1, db.TYP_CYKLICZNY_WYDATEK)
        )

        e_nazwa = ft.TextField(label="Nazwa (np. Rata leasingu, Sprawdź ciśnienie w oponach)", value=str(nazwa_val), **styl_pola())
        e_kwota = ft.TextField(label=f"Kwota ({symbol_waluty()})", value=str(kwota_val) if kwota_val else "", keyboard_type=ft.KeyboardType.NUMBER, **styl_pola())
        e_tylko_przypomnienie = ft.Switch(label="Tylko przypomnienie (bez kwoty)", value=not bool(czy_koszt_val))
        e_kwota.visible = not e_tylko_przypomnienie.value

        # Rodzaj wpisu. „Sezonowa zmiana opon” to jedyny rodzaj, który przy
        # odhaczeniu ZMIENIA DANE (montuje drugi komplet), więc dostaje własną
        # pozycję zamiast chować się jako zwykłe przypomnienie z nazwą „opony”.
        e_rodzaj = ft.Dropdown(
            label="Rodzaj wpisu",
            options=[
                ft.DropdownOption(key=db.TYP_CYKLICZNY_WYDATEK, text="Wydatek / czynność cykliczna"),
                ft.DropdownOption(key=db.TYP_CYKLICZNY_OPONY, text="Sezonowa zmiana opon"),
            ],
            value=typ_val if typ_val in db.TYPY_CYKLICZNE else db.TYP_CYKLICZNY_WYDATEK,
            **styl_dropdown()
        )
        podpowiedz_opon = ft.Text(
            "Po odhaczeniu aplikacja sama przestawi zamontowany zestaw opon na komplet z drugiego sezonu.",
            size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT,
        )

        def odswiez_rodzaj():
            czy_opony = e_rodzaj.value == db.TYP_CYKLICZNY_OPONY
            podpowiedz_opon.visible = czy_opony
            e_kwota.visible = not e_tylko_przypomnienie.value
            if not e_kwota.visible:
                ustaw_blad(e_kwota)
            if czy_opony and not (e_nazwa.value or "").strip():
                e_nazwa.value = "Sezonowa zmiana opon"
            try:
                page.update()
            except Exception:
                pass

        def przelacz_typ(e):
            odswiez_rodzaj()
        e_tylko_przypomnienie.on_change = przelacz_typ

        def przelacz_rodzaj(e):
            if e_rodzaj.value == db.TYP_CYKLICZNY_OPONY:
                # Zmiana opon wypada dwa razy w roku — podstawiamy pół roku,
                # żeby nie trzeba było tego poprawiać po każdym wyborze rodzaju.
                e_okres.value = "180"
                e_tylko_przypomnienie.value = True
            odswiez_rodzaj()
        # Dropdown w Flet 0.8x ma on_select, nie on_change (patrz utils/zgodnosc).
        e_rodzaj.on_select = przelacz_rodzaj

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
        e_data = pole_daty(page, "Następny termin", str(data_val))
        podpowiedz_opon.visible = e_rodzaj.value == db.TYP_CYKLICZNY_OPONY

        def zapisz(e):
            ustaw_blad(e_nazwa)
            ustaw_blad(e_kwota)
            n = (e_nazwa.value or "").strip()
            czy_koszt = not e_tylko_przypomnienie.value
            kw = parsuj_float(e_kwota.value, None) if czy_koszt else 0.0
            bledy = []
            if not n: bledy.append((e_nazwa, "Podaj nazwę"))
            if czy_koszt and (kw is None or kw <= 0): bledy.append((e_kwota, "Podaj poprawną kwotę"))
            if bledy:
                for kontrolka, komunikat in bledy: ustaw_blad(kontrolka, komunikat)
                page.update()
                return
            okres_dni = parsuj_int(e_okres.value, 30)
            typ = e_rodzaj.value if e_rodzaj.value in db.TYPY_CYKLICZNE else db.TYP_CYKLICZNY_WYDATEK
            if edycja:
                db.edytuj_wydatek_cykliczny(w_id, n, kw or 0.0, okres_dni, e_data.value, czy_koszt, typ)
            else:
                db.dodaj_wydatek_cykliczny(state.auto_id, n, kw or 0.0, okres_dni, e_data.value, czy_koszt, typ)
            zamknij_dialog(page, dlg)
            odswiez()

        dlg = ft.AlertDialog(
            title=ft.Text("Edytuj wpis" if edycja else "Nowy wydatek cykliczny / przypomnienie", weight="bold"),
            content=ft.Column(
                [e_nazwa, e_rodzaj, podpowiedz_opon, e_tylko_przypomnienie, e_kwota, e_okres, e_data],
                tight=True, spacing=10, scroll=ft.ScrollMode.AUTO,
            ),
            actions=[
                ft.TextButton("Anuluj", on_click=lambda e: zamknij_dialog(page, dlg)),
                ft.ElevatedButton("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY)
            ]
        )
        otworz_dialog(page, dlg)

    odswiez()
    otworz_dno(page, bs)


__all__ = [
    "_sygnatura_powiadomien",
    "etykieta_wykonania_cyklicznego",
    "ikona_wpisu_cyklicznego",
    "komunikat_zmiany_opon",
    "komunikat_po_wykonaniu",
    "pokaz_panel_powiadomien",
    "pokaz_panel_wydatkow_cyklicznych",
    "przycisk_dzwonka",
]
