"""Elementy związane z pojazdem: odznaka, tablica, terminy, kondycja."""

import db
import flet as ft

from datetime import datetime

from .animacje import ScenaWejscia
from .stale import FS, IKONY_NADWOZIA, KOLOR_STATUS, MAPA_KOLOROW, RADIUS, SPACING, formatuj_liczba, ikona_z_mapy
from .format import formatuj_dni, formatuj_dni_dopelniacz, parsuj_float, parsuj_int, symbol_waluty
from .zgodnosc import ustaw_blad
from .wyglad import powierzchnia, tlo_stanu, tlo_toru
from .dialogi import otworz_dialog, otworz_dno, pokaz_komunikat, pokaz_komunikat_cofnij, potwierdz, przejdz, zamknij_dialog, zamknij_dno
from .sync_ui import wypchnij_w_tle
from .formularze import pole_daty, sprawdz_podejrzany_przebieg, styl_pola
from .notatki import pole_notatki, zapisz_notatke_z_formularza
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
    okres = f"przez {formatuj_dni(dni)}" if dni else "bez limitu czasu"
    potwierdz(
        page, "Usunąć pojazd?",
        f"„{nazwa}” trafi do kosza wraz z całą historią serwisową i zdjęciami. "
        f"Będzie tam czekał {okres} — do tego czasu przywrócisz go jednym kliknięciem.",
        wykonaj,
        tekst_potwierdzenia="Przenieś do kosza",
    )


def sprzedaj_auto(page: ft.Page, state):
    """Wyprowadza pojazd z aktywnego garażu bez kasowania czegokolwiek.

    Dlaczego to NIE jest kosz: kosz trzyma migawkę JSON i istnieje po to, żeby
    cofnąć pomyłkę. Sprzedane auto to nie pomyłka — jego historia ma zostać
    czytelna i możliwa do wyeksportowania (rozliczenie z kupującym, gwarancje
    na części, porównanie z następnym autem), a nie zamrożona w archiwum.
    """
    if not state.auto_id:
        return
    auto_id = state.auto_id
    nazwa = state.auto_nazwa
    metryki = db.pobierz_metryki_pojazdu(auto_id) or {}

    e_data = pole_daty(page, "Data sprzedaży", datetime.now().strftime("%d.%m.%Y"))
    e_cena = ft.TextField(
        label=f"Cena sprzedaży ({symbol_waluty()}) — opcjonalnie",
        keyboard_type=ft.KeyboardType.NUMBER, **styl_pola()
    )

    podpowiedz = ["Auto zniknie z przełącznika pojazdów, ale cała historia zostaje — otworzysz ją w Archiwum."]
    if metryki.get("cena_zakupu"):
        podpowiedz.append(
            f"Cena zakupu: {formatuj_liczba(metryki['cena_zakupu'])} {symbol_waluty()}. "
            "Po podaniu ceny sprzedaży aplikacja policzy rzeczywistą utratę wartości zamiast szacunku."
        )

    def wykonaj(e):
        ustaw_blad(e_cena)
        cena = parsuj_float(e_cena.value, None) if (e_cena.value or "").strip() else None
        if cena is not None and cena < 0:
            ustaw_blad(e_cena, "Cena nie może być ujemna")
            page.update()
            return
        wynik = db.oznacz_pojazd_sprzedany(auto_id, e_data.value, cena)
        zamknij_dialog(page, dlg)
        if not wynik:
            return

        oryg_cofnij = wynik["cofnij"]

        def nowe_cofnij():
            oryg_cofnij()
            state.auto_id = auto_id
            db.zainicjuj_domyslne_auto(state)
            przejdz(page, "/")
        wynik["cofnij"] = nowe_cofnij

        # Po sprzedaży stoimy na aucie, którego nie ma już w garażu — przenosimy
        # się na pierwsze aktywne (albo na „Brak pojazdów”, jeśli to było ostatnie).
        state.auto_id = None
        db.zainicjuj_domyslne_auto(state)
        przejdz(page, "/")
        pokaz_komunikat_cofnij(page, f"„{nazwa}” przeniesiony do archiwum sprzedanych.", wynik)

    dlg = ft.AlertDialog(
        title=ft.Text(f"Sprzedaj „{nazwa}”?", weight="bold"),
        content=ft.Column(
            [e_data, e_cena] + [
                ft.Text(t, size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT) for t in podpowiedz
            ],
            tight=True, spacing=10,
        ),
        actions=[
            ft.TextButton("Anuluj", on_click=lambda e: zamknij_dialog(page, dlg)),
            ft.ElevatedButton("Przenieś do archiwum", on_click=wykonaj,
                              bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY),
        ],
    )
    otworz_dialog(page, dlg)


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
        return KOLOR_STATUS["neutral"], ft.Icons.HELP_OUTLINE, "Brak danych"
    if wynik >= 80:
        return KOLOR_STATUS["ok"], ft.Icons.FAVORITE, "Bardzo dobra"
    if wynik >= 50:
        return KOLOR_STATUS["warning"], ft.Icons.FAVORITE_BORDER, "Wymaga uwagi"
    return KOLOR_STATUS["critical"], ft.Icons.HEART_BROKEN, "Wymaga pilnej reakcji"


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
        bgcolor=tlo_toru(page),
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
                ft.Text("Podzespoły są w interwale, terminy dokumentów ważne, bieżnik "
                        "w normie, a dane aktualne.",
                        size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                        text_align=ft.TextAlign.CENTER),
            ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        ))
    else:
        zawartosc.append(ft.Text(
            f"Odjęto łącznie {100 - (wynik or 0)} pkt · {len(powody)} "
            + ("powód" if len(powody) == 1 else "powody" if len(powody) < 5 else "powodów"),
            size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
        ))

        # Grupa, która uderzyła w swój sufit, musi się do tego przyznać: bez tego
        # minusy z listy nie zsumują się do odjętych punktów i wygląda to na błąd.
        przyciete = [g for g in rozbicie.get("grupy", {}).values() if g.get("przyciete")]
        if przyciete:
            zawartosc.append(ft.Text(
                "Sufit grupy ograniczył karę — "
                + " · ".join(f"{g['etykieta']}: −{g['punkty']} zamiast −{g['surowe']}"
                             for g in przyciete),
                size=FS["caption"], italic=True, color=ft.Colors.ON_SURFACE_VARIANT,
            ))

        IKONY_POWODU = {
            "podzespol": ft.Icons.HANDYMAN, "opony": ft.Icons.TIRE_REPAIR,
            "dokument": ft.Icons.SHIELD, "usterka": ft.Icons.CHECKLIST_RTL,
            "licznik": ft.Icons.SPEED, "dane": ft.Icons.HELP_OUTLINE,
        }
        for p in powody:
            # Największe minusy pierwsze (sortuje db), a czerwień bierze się z WAGI
            # powodu, nie z liczby punktów: brak wpisanej daty OC kosztuje tyle samo,
            # co zbliżający się drobny termin, ale znaczy co innego.
            kolor_kary = (KOLOR_STATUS["critical"] if p.get("waga") == "krytyczna"
                          else KOLOR_STATUS["warning"])
            tresc = [ft.Text(p["opis"], size=FS["label"], weight="bold")]
            if p["szczegol"]:
                tresc.append(ft.Text(p["szczegol"], size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT))

            # Wiersz powodu leży W ŚRODKU panelu kondycji, więc jest blokiem,
            # a nie kartą: wystarczy tło o stopień wyżej.
            zawartosc.append(ft.Container(
                padding=ft.Padding(12, 12, 12, 12),
                **powierzchnia(page, "blok"),
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
            "Kondycja liczy stan techniczny i terminy, które blokują jazdę: podzespoły po "
            "interwale, bieżnik, dokumenty, zaległe usterki oraz braki i ciszę w danych. Każda "
            "grupa ma własny sufit, żeby seria drobiazgów nie ważyła tyle, co brak ważnego OC. "
            "Magazyn i wydatki cykliczne jej nie ruszają.",
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
    "po_terminie": KOLOR_STATUS["critical"],
    "blisko": KOLOR_STATUS["warning"],
    "ok": KOLOR_STATUS["ok"],
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


def pasek_terminu(page: ft.Page, termin, pelny=True, scena=None):
    """Wiersz terminu dokumentu z odliczaniem i paskiem. Pasek pokazuje, ile
    z okna ostrzegawczego już minęło — wypełnia się dopiero, gdy termin wchodzi
    w próg powiadomienia, więc „zielony i pusty” znaczy „jeszcze długo”.

    To dobra decyzja, ale trudna do odczytania z jednego spojrzenia: pusty pasek
    wygląda jak brak danych. `scena` (utils.ScenaWejscia) każe mu przy wejściu
    wypełnić się od zera — wtedy widać, GDZIE się zatrzymał, a to jest cała
    treść. Termin jeszcze odległy nie drgnie wcale i właśnie to o nim mówi."""
    scena = scena or ScenaWejscia(wlaczona=False)
    scena.nastepny_wiersz()
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
        elementy.append(scena.wskaznik(ft.ProgressBar(
            value=udzial, color=kolor,
            bgcolor=tlo_toru(page),
            height=6, border_radius=3,
        )))
        elementy.append(ft.Row([
            ft.Icon(ikona_z_mapy(IKONY_STATUSU_TERMINU, termin["status"], ft.Icons.EVENT),
                    size=12, color=kolor),
            ft.Text(opis_dni_terminu(termin["dni"]), size=FS["caption"], color=kolor, expand=True),
        ], spacing=4))

    return ft.Column(elementy, spacing=SPACING["xs"])


def dialog_odczytu_przebiegu(page: ft.Page, auto_id, odczyt=None, po_zapisie=None):
    """Okno „stan licznika”: data, przebieg i notatka. `odczyt` None znaczy nowy
    wpis, słownik z pobierz_pelna_historie_przebiegu — edycję WŁASNEGO odczytu
    (pozostałe wpisy mają swoje formularze i to tam się je poprawia).

    Mieszka w utils, bo wołają je dwa miejsca: ekran „Historia licznika” i kafelek
    akcji na kokpicie. Druga kopia tego formularza rozjechałaby się z pierwszą
    przy pierwszej poprawce walidacji.

    `po_zapisie` dostaje kontrolę po udanym zapisie: ekran licznika przeładowuje
    się trasą, kokpit tylko przebudowuje to, co widać."""
    edycja = odczyt is not None
    domyslna_data = odczyt["data"] if edycja else datetime.now().strftime("%d.%m.%Y")
    domyslny_przebieg = (str(odczyt["przebieg"]) if edycja
                         else str(db.pobierz_aktualny_przebieg(auto_id) or ""))
    notatka_bazowa = str((odczyt.get("notatka") if edycja else "") or "")

    e_data = pole_daty(page, "Data odczytu", domyslna_data)
    e_notatka = pole_notatki(notatka_bazowa, page)
    e_przebieg = ft.TextField(
        label="Przebieg (km)", value=domyslny_przebieg,
        keyboard_type=ft.KeyboardType.NUMBER, autofocus=not edycja,
        **styl_pola()
    )

    def zapisz(e):
        ustaw_blad(e_przebieg)
        nowy = parsuj_int(e_przebieg.value, None)
        if nowy is None or nowy <= 0:
            ustaw_blad(e_przebieg, "Podaj poprawny przebieg")
            page.update()
            return

        wyklucz = odczyt["id"] if edycja else None
        if sprawdz_podejrzany_przebieg(page, e_przebieg, auto_id, nowy,
                                       wyklucz_id=wyklucz, tabela="odczyty_przebiegu",
                                       nowa_data_str=e_data.value):
            return

        zamknij_dialog(page, dlg)
        if edycja:
            db.aktualizuj_odczyt_przebiegu(odczyt["id"], nowy, e_data.value)
            zapisz_notatke_z_formularza("odczyty_przebiegu", odczyt["id"],
                                        e_notatka.value, notatka_bazowa)
            pokaz_komunikat(page, "Zapisano zmiany!")
        else:
            nadpisano = db.dodaj_odczyt_przebiegu(auto_id, nowy, e_data.value,
                                                  e_notatka.value, zrodlo="reczny")
            pokaz_komunikat(page, "Zaktualizowano odczyt z tego dnia!" if nadpisano
                            else "Dodano odczyt przebiegu!")
        wypchnij_w_tle(page, auto_id, "odczyt przebiegu")
        if po_zapisie:
            po_zapisie()

    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Row([ft.Icon(ft.Icons.SPEED, color=ft.Colors.PRIMARY),
                      ft.Text("Edycja odczytu" if edycja else "Nowy odczyt", weight="bold", expand=True)], spacing=8),
        content=ft.Column([
            e_data,
            e_przebieg,
            e_notatka,
            ft.Text(
                "Jeśli dla wybranej daty istnieje już odczyt, zostanie zaktualizowany. "
                "Przebiegi z tankowań, wizyt i serwisu pojawiają się w historii same.",
                size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT, visible=not edycja
            )
        ], tight=True, spacing=10),
        actions=[
            ft.TextButton("Anuluj", on_click=lambda e: zamknij_dialog(page, dlg)),
            ft.ElevatedButton("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY)
        ],
        actions_alignment=ft.MainAxisAlignment.END
    )
    otworz_dialog(page, dlg)


def baner_nieswiezego_licznika(page: ft.Page, auto_id, swiezosc, po_zapisie=None,
                               tresc=None, tekst_przycisku="Wpisz stan"):
    """Pasek „licznik jest nieświeży” nad tym, co się z licznika liczy (zakładka
    Serwis, Historia licznika). Jeden wygląd w obu miejscach, bo mówi to samo.

    None, gdy licznik jest świeży albo auto nie ma jeszcze żadnego przebiegu —
    tym drugim zajmują się dzwonek i pusty stan ekranu. Przycisk wpisu dostaje
    tylko ten, kto może dopisywać; podgląd widzi samo ostrzeżenie."""
    if not swiezosc or not swiezosc.get("nieswiezy") or swiezosc.get("dni") is None:
        return None
    kolor = KOLOR_STATUS["warning"]
    tresc = tresc or f"Prognozy km liczone z licznika sprzed {formatuj_dni_dopelniacz(swiezosc['dni'])}"
    elementy = [
        ft.Icon(ft.Icons.SPEED, size=18, color=kolor),
        ft.Text(tresc, size=FS["caption"], color=kolor, expand=True),
    ]
    if db.czy_moge_dodawac(auto_id):
        elementy.append(ft.TextButton(
            tekst_przycisku, icon=ft.Icons.EDIT,
            on_click=lambda e: dialog_odczytu_przebiegu(page, auto_id, po_zapisie=po_zapisie),
        ))
    return ft.Container(
        padding=ft.Padding(12, 4, 4, 4), border_radius=RADIUS["sm"],
        bgcolor=tlo_stanu(page, "warning"),
        content=ft.Row(elementy, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )


__all__ = [
    "IKONY_STATUSU_TERMINU",
    "IKONY_TERMINOW",
    "KOLORY_STATUSU_TERMINU",
    "baner_nieswiezego_licznika",
    "dialog_odczytu_przebiegu",
    "ikona_nadwozia",
    "odznaka_pojazdu",
    "opis_dni_terminu",
    "pasek_terminu",
    "pokaz_panel_kondycji",
    "sprzedaj_auto",
    "tablica_rejestracyjna",
    "usun_auto",
    "wskaznik_kondycji",
]
