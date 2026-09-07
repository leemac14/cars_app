"""Wspólne kontrolki: tagi, kolory, wybór warsztatu i stacji, karty, FAB."""

import asyncio
import db
import flet as ft
import inspect
import urllib.parse

from .stale import (
    FS, IKONY_OBSERWACJI, KOLORY_TONU, KOLOR_STATUS, MAPA_KOLOROW, RADIUS, SPACING,
    ikona_kategorii_innych, ikona_z_mapy, kolor_kategorii_innych,
)
from .wyglad import powierzchnia_karty, tlo_karty
from .zgodnosc import ustaw_blad
from .dialogi import otworz_dialog, potwierdz, przejdz, zamknij_dialog
from .formularze import styl_dropdown, styl_pola
from .system import kopiuj_do_schowka, zadzwon


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
                        ustaw_blad(e_nazwa)
                        nowa_nazwa = (e_nazwa.value or "").strip()
                        
                        if "," in nowa_nazwa:
                            ustaw_blad(e_nazwa, "Nazwa nie może zawierać przecinków")
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
            ustaw_blad(e_nazwa)
            n = (e_nazwa.value or "").strip()
            
            if "," in n:
                ustaw_blad(e_nazwa, "Nazwa nie może zawierać przecinków")
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


def odznaka_kategorii_innych(kategoria, rozmiar_ikony=14):
    """Chip kategorii innego kosztu: ikona + nazwa. Celowo wygląda inaczej niż
    tagi (ikona, stonowane tło) — kategoria jest jedna i wybierana ze słownika,
    tagi są dowolne i może ich być wiele, więc nie powinny się zlewać."""
    etykieta = str(kategoria or "").strip() or "Ogólne"
    kolor = kolor_kategorii_innych(etykieta)
    return ft.Container(
        padding=ft.Padding(8, 3, 10, 3),
        border_radius=RADIUS["pill"],
        bgcolor=ft.Colors.with_opacity(0.12, kolor),
        content=ft.Row([
            ft.Icon(ikona_kategorii_innych(etykieta), size=rozmiar_ikony, color=kolor),
            ft.Text(etykieta, size=FS["caption"], weight="bold", color=kolor),
        ], spacing=5, tight=True),
    )


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
            ft.Text(" | ".join(fragmenty), size=11, color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
        ], spacing=4),
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

    btn_dzwon = ft.OutlinedButton("Zadzwoń", icon=ft.Icons.PHONE, visible=False)
    btn_nawiguj = ft.OutlinedButton("Nawiguj", icon=ft.Icons.NAVIGATION, visible=False)
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

    # ft.Dropdown reaguje na `on_select`, nie na `on_change` (Flet 0.86) — bez tego
    # wybór warsztatu z listy nie podstawiał jego telefonu ani adresu, więc przyciski
    # „Zadzwoń” i „Nawiguj” nigdy się nie pojawiały.
    e_dropdown.on_select = po_zmianie

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


def komponent_wyboru_stacji(page: ft.Page, state, aktualna_nazwa="", elektryczny=False):
    """Wybór stacji paliw z listy tych, na których już tankowałeś (słownik
    budowany w locie z tabeli 'tankowania' — patrz db.pobierz_stacje_paliw),
    z możliwością przełączenia na ręczne wpisanie nowej nazwy. Ten sam wzorzec
    co komponent_wyboru_warsztatu. Dzięki temu 'Orlen', 'orlen' i 'ORLEN'
    nie rozjeżdżają rankingu cen (db.pobierz_trend_cen_paliwa).
    Zwraca (kontener, pobierz_wartosc, ustaw_wartosc)."""
    etyk = db.etykiety_paliwa(elektryczny)
    cache_stacji = {"dane": None}

    def nazwy_stacji():
        # Cache w obrębie życia komponentu — lista nie zmienia się, dopóki
        # formularz jest otwarty, więc wystarczy jeden SELECT.
        if cache_stacji["dane"] is None:
            cache_stacji["dane"] = db.pobierz_stacje_paliw(state.auto_id)
        return cache_stacji["dane"]

    biezaca = " ".join((aktualna_nazwa or "").split())
    pasuje_start = biezaca in nazwy_stacji()

    # Tryb ręczny: wpis spoza słownika ALBO brak jakiejkolwiek zapisanej stacji
    # (pierwsze tankowanie — pusty dropdown byłby ślepą uliczką).
    pokaz_reczne = bool(biezaca and not pasuje_start) or not nazwy_stacji()

    def zbuduj_opcje():
        opcje = [ft.DropdownOption(key="", text="— Nie podano —")]
        for nazwa in nazwy_stacji():
            opcje.append(ft.DropdownOption(key=nazwa, text=nazwa))
        return opcje

    e_dropdown = ft.Dropdown(
        label=etyk["punkt_opcjonalnie"],
        options=zbuduj_opcje(),
        value=biezaca if pasuje_start else "",
        visible=not pokaz_reczne,
        expand=True,
        **styl_dropdown()
    )

    e_recznie = ft.TextField(
        label=etyk["punkt_recznie"],
        hint_text=etyk["punkt_hint"],
        value=biezaca if pokaz_reczne else "",
        visible=pokaz_reczne,
        expand=True,
        **styl_pola()
    )

    btn_zmien_tryb = ft.IconButton(
        icon=ft.Icons.LIST if pokaz_reczne else ft.Icons.EDIT,
        tooltip=f"Wybierz {etyk['punkt'].lower()} z listy" if pokaz_reczne else "Wpisz nową nazwę ręcznie",
        icon_color=ft.Colors.PRIMARY
    )

    wiersz = ft.Row(
        [e_dropdown, e_recznie, btn_zmien_tryb],
        vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=10
    )

    def _tryb_listy():
        e_dropdown.visible = True
        e_recznie.visible = False
        btn_zmien_tryb.icon = ft.Icons.EDIT
        btn_zmien_tryb.tooltip = "Wpisz nową stację ręcznie"

    def _tryb_reczny():
        e_dropdown.visible = False
        e_recznie.visible = True
        btn_zmien_tryb.icon = ft.Icons.LIST
        btn_zmien_tryb.tooltip = "Wybierz stację z listy"

    def przelacz_tryb(e):
        if e_recznie.visible:
            wpisana = " ".join((e_recznie.value or "").split())
            e_dropdown.options = zbuduj_opcje()
            e_dropdown.value = wpisana if wpisana in nazwy_stacji() else ""
            _tryb_listy()
        else:
            e_recznie.value = e_dropdown.value or ""
            _tryb_reczny()
        try:
            wiersz.update()
        except Exception:
            pass

    btn_zmien_tryb.on_click = przelacz_tryb

    def dopasuj_do_slownika(tekst):
        """Zwraca istniejącą pisownię stacji, jeśli wpisany tekst to tylko inny
        wariant zapisu ('orlen' -> 'Orlen'). W przeciwnym razie zwraca tekst."""
        czysty = " ".join((tekst or "").split())
        if not czysty:
            return ""
        klucz = db.klucz_stacji(czysty)
        for nazwa in nazwy_stacji():
            if db.klucz_stacji(nazwa) == klucz:
                return nazwa
        return czysty

    def pobierz_wartosc():
        if e_recznie.visible:
            return dopasuj_do_slownika(e_recznie.value)
        return e_dropdown.value or ""

    def ustaw_wartosc(nazwa):
        """Wpisanie wartości z zewnątrz (np. rozpoznanej z paragonu przez OCR)."""
        dopasowana = dopasuj_do_slownika(nazwa)
        if dopasowana and dopasowana in nazwy_stacji():
            e_dropdown.options = zbuduj_opcje()
            e_dropdown.value = dopasowana
            e_recznie.value = ""
            _tryb_listy()
        else:
            e_recznie.value = dopasowana
            _tryb_reczny()
        try:
            wiersz.update()
        except Exception:
            pass

    return wiersz, pobierz_wartosc, ustaw_wartosc


def tytul_sekcji(ikona, tekst, kolor=None, rozmiar=20):
    """Ikona + tytuł sekcji jako gotowa PARA kontrolek do wstawienia w ft.Row.
    Zwraca listę, bo nagłówki sekcji doklejają sobie z prawej filtry, liczniki
    i przyciski akcji."""
    kolor = kolor or ft.Colors.PRIMARY
    return [
        ft.Icon(ikona, size=rozmiar, color=kolor),
        ft.Text(tekst, size=rozmiar, weight="bold", color=kolor, expand=True),
    ]


def chipy_kwot(pary, rozmiar=12, kolor=None, odstep=8):
    """Wiersz „ikona + kwota” dla kilku kategorii naraz — zamiennik dawnych
    sklejek typu "⛽ 320 • 🛠️ 140". Każda para to (ikona, tekst); puste pary
    (None) są pomijane. Zwraca None, jeśli nie ma czego pokazać."""
    kolor = kolor or ft.Colors.ON_SURFACE_VARIANT
    kontrolki = []
    for para in pary:
        if not para:
            continue
        ikona, tekst = para
        kontrolki.append(ft.Row([
            ft.Icon(ikona, size=rozmiar + 1, color=kolor),
            ft.Text(str(tekst), size=rozmiar, color=kolor, no_wrap=True),
        ], spacing=3, tight=True))
    if not kontrolki:
        return None
    return ft.Row(kontrolki, spacing=odstep, tight=True, wrap=True)


def znacznik_wykonania(page: ft.Page, tekst="Gotowe", po_zakonczeniu=None, pauza=0.7):
    """Krótki „moment satysfakcji” wstawiany W MIEJSCE przycisku po oznaczeniu
    czegoś jako załatwione: ptaszek wskakuje ze skalą i przygasza się w miejsce
    napisu. Po `pauza` sekundach woła `po_zakonczeniu` (zwykle odświeżenie
    listy), więc animacja zdąży się pokazać, zanim wiersz zniknie."""
    pudelko = ft.Container(
        padding=ft.Padding.symmetric(horizontal=8, vertical=4),
        scale=0.5, opacity=0.0,
        animate_scale=ft.Animation(280, ft.AnimationCurve.EASE_OUT_BACK),
        animate_opacity=ft.Animation(180, ft.AnimationCurve.EASE_OUT),
        content=ft.Row([
            ft.Icon(ft.Icons.CHECK_CIRCLE, size=18, color=KOLOR_STATUS["ok"]),
            ft.Text(tekst, size=FS["label"], weight="bold", color=KOLOR_STATUS["ok"], no_wrap=True),
        ], spacing=5, tight=True),
    )

    async def _odegraj():
        # Jedna klatka zwłoki: gdyby stan docelowy ustawić od razu, Flet wysłałby
        # do klienta wyłącznie wartość końcową i animacja nie miałaby z czego wyjść.
        await asyncio.sleep(0.03)
        pudelko.scale = 1.0
        pudelko.opacity = 1.0
        try:
            page.update()
        except Exception:
            pass
        if po_zakonczeniu:
            await asyncio.sleep(pauza)
            try:
                po_zakonczeniu()
            except Exception:
                pass

    page.run_task(_odegraj)
    return pudelko


def wiersz_danych(page: ft.Page, ikona, etykieta, wartosc, kopiowalne=False, telefon=False,
                  podpowiedz=None):
    """Jeden wiersz danych pojazdu: ikona, etykieta, wartość. Wartość długa
    i przepisywana ręcznie (VIN, numer polisy) dostaje przycisk kopiowania,
    numer telefonu — przycisk dzwonienia. Puste pole zostaje widoczne z myślnikiem,
    bo brak informacji też jest informacją: wiadomo, co warto uzupełnić."""
    tekst = str(wartosc).strip() if wartosc not in (None, "") else ""
    kolumna = [
        ft.Text(etykieta, size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT),
        ft.Text(tekst or "—", size=FS["body_strong"],
                weight="bold" if tekst else "normal",
                color=ft.Colors.ON_SURFACE if tekst else ft.Colors.ON_SURFACE_VARIANT,
                selectable=bool(tekst)),
    ]
    if podpowiedz and tekst:
        kolumna.append(ft.Text(podpowiedz, size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT))

    akcje = []
    if tekst and telefon:
        akcje.append(ft.IconButton(
            ft.Icons.PHONE, icon_size=18, icon_color=ft.Colors.GREEN_700, tooltip="Zadzwoń",
            on_click=lambda e: zadzwon(page, tekst), style=ft.ButtonStyle(padding=0),
            width=34, height=34,
        ))
    if tekst and kopiowalne:
        akcje.append(ft.IconButton(
            ft.Icons.COPY, icon_size=16, icon_color=ft.Colors.ON_SURFACE_VARIANT, tooltip="Kopiuj",
            on_click=lambda e: kopiuj_do_schowka(page, tekst, f"Skopiowano: {etykieta}"),
            style=ft.ButtonStyle(padding=0), width=34, height=34,
        ))

    return ft.Row(
        [ft.Icon(ikona, size=18, color=ft.Colors.ON_SURFACE_VARIANT),
         ft.Column(kolumna, spacing=0, expand=True)] + akcje,
        spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def karta_obserwacji(page: ft.Page, obserwacja, kompaktowa=False, on_click=None):
    """Pojedyncze spostrzeżenie z db.obserwacje_analityczne jako karta:
    kolorowa ikona po lewej, tytuł i zdanie po prawej. Kolor niesie ton, więc
    „budżet przekroczony” widać zanim się przeczyta treść."""
    if not obserwacja:
        return ft.Container(width=0, height=0)

    kolor = KOLORY_TONU.get(obserwacja.get("ton"), ft.Colors.BLUE_GREY_700)
    ikona = ikona_z_mapy(IKONY_OBSERWACJI, obserwacja.get("ikona"), ft.Icons.INSIGHTS)
    trasa = obserwacja.get("trasa")
    akcja = on_click or ((lambda e: przejdz(page, trasa)) if trasa else None)

    tresc = [
        ft.Text(obserwacja.get("tytul", ""), size=FS["label"], weight="bold", color=kolor),
        ft.Text(obserwacja.get("tekst", ""), size=FS["body"], color=ft.Colors.ON_SURFACE,
                max_lines=3 if kompaktowa else None,
                overflow=ft.TextOverflow.ELLIPSIS if kompaktowa else None),
    ]

    return ft.Container(
        padding=SPACING["md"], border_radius=RADIUS["lg"],
        bgcolor=ft.Colors.with_opacity(0.07, kolor),
        border=ft.Border.only(left=ft.BorderSide(3, kolor)),
        ink=bool(akcja), on_click=akcja,
        content=ft.Row([
            ft.Container(
                width=36, height=36, border_radius=RADIUS["md"],
                bgcolor=ft.Colors.with_opacity(0.16, kolor),
                alignment=ft.Alignment.CENTER,
                content=ft.Icon(ikona, size=19, color=kolor),
            ),
            ft.Column(tresc, spacing=2, expand=True),
        ], spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )


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
            border=powierzchnia["border"],
            content=kontener,
        )
        return karta, kontener

    karta = ft.Container(
        border_radius=RADIUS["lg"], clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        shadow=powierzchnia["shadow"],
        border=powierzchnia["border"],
        content=ft.Row([ft.Container(width=4, bgcolor=kolor_paska), kontener], spacing=0),
    )
    return karta, kontener


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
    opcje: lista (etykieta, indeks) albo (etykieta, indeks, ikona) — ikona jest
    opcjonalna i pojawia się przed podpisem. on_zmiana(nowy_idx) wywoływane po
    kliknięciu."""
    segmenty = []
    for opcja in opcje:
        etykieta, idx = opcja[0], opcja[1]
        ikona = opcja[2] if len(opcja) > 2 else None
        aktywny = (idx == aktywny_idx)
        kolor_tresci = ft.Colors.ON_PRIMARY if aktywny else ft.Colors.ON_SURFACE_VARIANT
        podpis = ft.Text(etykieta, size=FS["label"], weight="bold", color=kolor_tresci)
        tresc = podpis if not ikona else ft.Row(
            [ft.Icon(ikona, size=16, color=kolor_tresci), podpis],
            spacing=6, tight=True, alignment=ft.MainAxisAlignment.CENTER,
        )
        segmenty.append(
            ft.Container(
                expand=True, height=36, alignment=ft.Alignment.CENTER,
                border_radius=RADIUS["pill"], ink=True,
                bgcolor=ft.Colors.PRIMARY if aktywny else ft.Colors.TRANSPARENT,
                animate=ft.Animation(220, ft.AnimationCurve.EASE_OUT),
                animate_scale=ft.Animation(220, ft.AnimationCurve.EASE_OUT),
                scale=1.0 if aktywny else 0.96,
                on_click=lambda e, i=idx: on_zmiana(i),
                content=tresc,
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


__all__ = [
    "chipy_kwot",
    "ekran_braku_danych",
    "fab_animowany",
    "fab_speed_dial",
    "karta_listy",
    "karta_obserwacji",
    "komponent_tagow",
    "komponent_wyboru_koloru",
    "komponent_wyboru_stacji",
    "komponent_wyboru_warsztatu",
    "odznaka_kategorii_innych",
    "segmented_control",
    "tytul_sekcji",
    "wiersz_danych",
    "wizualizacja_tagow",
    "z_efektem_nacisniecia",
    "z_odswiezaniem",
    "znacznik_atrybucji",
    "znacznik_wykonania",
]
