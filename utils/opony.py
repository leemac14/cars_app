"""Opony na ekranie: kolory i pasek bieżnika, schemat kół, linijki kompletu, okno zmiany opon (dzień,
licznik, koszt, warsztat → db.zmien_opony z „Cofnij”), okno „Od kiedy na aucie?” i poprawka okresu
montażu. Liczby, progi i prognoza — db/opony.py."""

from datetime import datetime

import flet as ft

import db

from .stale import FS, IKONY_SEZONU_OPON, KOLOR_STATUS, KOLORY_SEZONU_OPON, RADIUS, SPACING, formatuj_liczba
from .format import formatuj_dystans, jednostka_dystansu, kolor_i_tekst_terminu, parsuj_float, symbol_waluty
from .typografia import etykieta, podpis, wartosc
from .wyglad import powierzchnia, tlo_stanu
from .dialogi import otworz_dialog, pokaz_komunikat, przejdz, zamknij_dialog
from .zgodnosc import ustaw_blad
from .sync_ui import wypchnij_w_tle, zablokowane
from .formularze import na_cala_szerokosc, pole_daty, pole_wyboru, sprawdz_podejrzany_przebieg, styl_pola
from .magazyn import liczba_do_pola
from .wykresy import pasek_postepu


# Status bieżnika i wieku (db/opony.py) -> rola w KOLOR_STATUS.
ROLE_BIEZNIKA = {db.STATUS_BIEZNIKA_OK: "ok", db.STATUS_BIEZNIKA_UWAGA: "warning",
                 db.STATUS_BIEZNIKA_KRYTYCZNY: "critical"}
ROLE_WIEKU = {db.STATUS_WIEKU_KONTROLA: "warning", db.STATUS_WIEKU_WYMIANA: "critical"}
NAZWY_KOL = {"lp": "Lewy przód", "pp": "Prawy przód", "lt": "Lewy tył", "pt": "Prawy tył"}
OSIE_SLOWAMI = {"Wszystkie": "na całym aucie", "Przód": "na przedniej osi", "Tył": "na tylnej osi"}


def kolor_bieznika(status):
    rola = ROLE_BIEZNIKA.get(status)
    return KOLOR_STATUS[rola] if rola else ft.Colors.ON_SURFACE_VARIANT


def kolor_wieku(wiek):
    rola = ROLE_WIEKU.get((wiek or {}).get("status"))
    return KOLOR_STATUS[rola] if rola else None


def stan_kompletu(komplet):
    """Stan podnoszący kartę kompletu: najgorszy z bieżnika i wieku do wymiany (None — spokojnie).
    Wiek „do kontroli” mówi sam napis — pięcioletnia opona to codzienność, nie alarm całej karty."""
    wiek = (komplet["wiek"] or {}).get("status")
    role = [ROLE_BIEZNIKA.get(komplet["status_bieznika"]),
            ROLE_WIEKU.get(wiek) if wiek == db.STATUS_WIEKU_WYMIANA else None]
    if "critical" in role:
        return "critical"
    return "warning" if "warning" in role else None


def nazwa_kompletu(komplet):
    return f"Opony {komplet['sezon'].lower()}" if komplet.get("sezon") else "Komplet opon"


def opis_kompletu(komplet):
    """„Michelin Alpin 6 · 205/55 R16” albo None."""
    return " · ".join(x for x in (komplet.get("marka_model"), komplet.get("rozmiar")) if x) or None


def tekst_zakresu_bieznika(pomiar):
    """„6,6 mm” albo „6,6–7,1 mm” (najpłytsze i najgłębsze koło)."""
    if not pomiar or pomiar["min"] is None:
        return None
    if pomiar["max"] is None or round(pomiar["max"] - pomiar["min"], 1) == 0:
        return db.tekst_bieznika(pomiar["min"])
    return f"{formatuj_liczba(pomiar['min'], 1)}–{db.tekst_bieznika(pomiar['max'])}"


def pasek_bieznika(komplet, scena=None):
    """Pasek „Bieżnik … 6,6–7,1 mm”: część bieżnika do minimum prawnego w kolorze statusu sezonu."""
    pomiar = komplet["ostatni_pomiar"]
    if not pomiar or pomiar["min"] is None:
        return podpis("Bieżnik niezmierzony — dodaj pomiar, a policzę tempo zużycia", max_lines=2)
    return pasek_postepu("Bieżnik", tekst_zakresu_bieznika(pomiar), komplet["udzial"] or 0.0,
                         kolor_bieznika(komplet["status_bieznika"]), wysokosc=6, scena=scena)


def linijka_kompletu(komplet, j=None, z_miejscem=True):
    """„3 lata · 18 400 km · Garaż · na felgach” — wiek, kilometry na komplecie, przechowalnia."""
    czesci = []
    wiek = db.tekst_wieku(komplet["wiek"])
    if wiek:
        czesci.append(wiek)
    if komplet["km"]:
        czesci.append(formatuj_dystans(komplet["km"], 0, j))
    if z_miejscem and komplet.get("miejsce") and not komplet["zamontowany"]:
        czesci.append(komplet["miejsce"])
    if komplet.get("na_felgach"):
        czesci.append("na felgach")
    return " · ".join(czesci) or None


def opis_wieku(wiek, z_wiekiem=True):
    """Zdanie o wieku dla karty i okna zmiany albo None przy oponach młodszych niż 5 lat; `z_wiekiem=False`
    — sama rada (wiek stoi już obok)."""
    if not wiek or wiek["status"] == db.STATUS_WIEKU_OK:
        return None
    if wiek["status"] == db.STATUS_WIEKU_WYMIANA:
        rada = f"producenci zalecają wymianę po {db.WIEK_WYMIANY_OPON} latach"
    else:
        rada = "niech wulkanizator obejrzy je przy zmianie"
    return f"{db.tekst_wieku(wiek)} od produkcji — {rada}" if z_wiekiem else rada


def opis_bieznika_ponizej(komplet):
    status = komplet["status_bieznika"]
    if status == db.STATUS_BIEZNIKA_KRYTYCZNY:
        return f"bieżnik poniżej minimum prawnego ({db.tekst_bieznika(db.BIEZNIK_MINIMUM_PRAWNE)})"
    if status == db.STATUS_BIEZNIKA_UWAGA:
        return f"bieżnik poniżej zalecanych {db.tekst_bieznika(komplet['prog_wymiany'])} — czas na nowe"
    return None


def wskazowka_osi(komplet):
    """„Przód zużywa się szybciej o 0,6 mm — przy zmianie zamień osie” albo None."""
    roznica = komplet.get("roznica_osi")
    if roznica is None or abs(roznica) < db.ROZNICA_OSI_ZAMIANY:
        return None
    os = "Przód" if roznica < 0 else "Tył"
    return f"{os} zużywa się szybciej o {db.tekst_bieznika(abs(roznica))} — przy zmianie zamień osie"


def schemat_kol(page, pomiar, sezon, kompaktowy=False):
    """Cztery koła jak na aucie widzianym z góry (przód na górze): bieżnik każdego w kolorze statusu."""
    kola = (pomiar or {}).get("kola") or {}

    def kolo(pozycja):
        mm = kola.get(pozycja)
        kolor = kolor_bieznika(db.status_bieznika(mm, sezon)) if mm is not None else ft.Colors.ON_SURFACE_VARIANT
        return ft.Container(
            expand=True, padding=ft.Padding(10, 6 if kompaktowy else 10, 10, 6 if kompaktowy else 10),
            **powierzchnia(page, "blok"),
            content=ft.Column([
                etykieta(db.SKROTY_KOL[pozycja]),
                wartosc(db.tekst_bieznika(mm) if mm is not None else "—", color=kolor if mm is not None else None),
            ], spacing=0, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        )

    return ft.Column([
        etykieta("przód"),
        ft.Row([kolo("lp"), kolo("pp")], spacing=SPACING["sm"]),
        ft.Row([kolo("lt"), kolo("pt")], spacing=SPACING["sm"]),
        etykieta("tył"),
    ], spacing=SPACING["xs"], horizontal_alignment=ft.CrossAxisAlignment.CENTER)


def chip_kompletu(page, komplet):
    """„Na aucie” (z osią) albo „W magazynie” — odznaka w rogu karty."""
    if komplet["zamontowany"]:
        tekst = "Na aucie" if komplet["os"] == "Wszystkie" else f"Na aucie: {komplet['os'].lower()}"
        return ft.Container(padding=ft.Padding(10, 4, 10, 4), border_radius=RADIUS["xl"],
                            bgcolor=tlo_stanu(page, "ok"),
                            content=ft.Text(tekst, size=FS["caption"], weight="bold", color=KOLOR_STATUS["ok"]))
    return ft.Container(padding=ft.Padding(10, 4, 10, 4), border_radius=RADIUS["xl"],
                        **{k: v for k, v in powierzchnia(page, "blok").items() if k == "bgcolor"},
                        content=etykieta("W magazynie"))


def ikona_sezonu(sezon, rozmiar=18):
    return ft.Icon(IKONY_SEZONU_OPON.get(sezon or "", ft.Icons.TIRE_REPAIR), size=rozmiar,
                   color=KOLORY_SEZONU_OPON.get(sezon or "", ft.Colors.PRIMARY))


def kandydat_zmiany(auto_id):
    """Komplet, który założy sezonowa zmiana (drugi sezon, najgrubszy bieżnik) albo None."""
    stan = db.pobierz_stan_opon(auto_id) or {}
    kandydaci = stan.get("kandydaci") or []
    if not kandydaci:
        return None

    def waga(z):
        return (-(parsuj_float(z["bieznik"], None) or 0.0), z["id"])

    return sorted(kandydaci, key=waga)[0]["id"]


# ============================================================================
#  KOMUNIKAT I „COFNIJ”
# ============================================================================

def komunikat_zmiany(wynik):
    """„Założono opony zimowe — Michelin Alpin 6 (zdjęto: letnie). Wpis jest w Serwisie…”."""
    if not wynik or not wynik.get("ok"):
        if (wynik or {}).get("powod") == "juz_na_aucie":
            return "Ten komplet jest już na tej osi."
        return "Nie zmieniono opon: kompletu już nie ma albo nie masz uprawnień."
    os = "" if wynik["os"] == "Wszystkie" else f" {OSIE_SLOWAMI[wynik['os']]}"
    tekst = f"Założono opony {str(wynik['na'] or '').lower()}{os}"
    if wynik.get("opis_zestawu"):
        tekst += f" — {wynik['opis_zestawu']}"
    if wynik.get("z"):
        tekst += f" (zdjęto: {wynik['z'].lower()})"
    tekst += "."
    if wynik.get("historia_id"):
        tekst += " Zmiana jest w Serwisie."
    elif wynik.get("koszt_id"):
        tekst += " Koszt jest w Innych kosztach."
    if wynik.get("termin_przesuniety") and wynik.get("nastepna_data"):
        tekst += f" Następna zmiana: {wynik['nastepna_data']}."
    return tekst


def pokaz_komunikat_zmiany(page, wynik, po_cofnieciu=None):
    """Komunikat po zmianie z „Cofnij” (6 s): wraca do kompletów, okresów i terminu sprzed zmiany."""
    if not wynik or not wynik.get("ok"):
        pokaz_komunikat(page, komunikat_zmiany(wynik), KOLOR_STATUS["warning"])
        return

    def cofnij(e):
        if db.cofnij_zmiane_opon(wynik["cofniecie"]):
            pokaz_komunikat(page, "Cofnięto zmianę opon.")
        else:
            pokaz_komunikat(page, "Nie cofnięto: w międzyczasie opony zmieniły się jeszcze raz.", KOLOR_STATUS["warning"])
        if po_cofnieciu:
            po_cofnieciu()
        else:
            przejdz(page, page.route)

    snack = ft.SnackBar(ft.Text(komunikat_zmiany(wynik)), bgcolor=KOLOR_STATUS["ok"], action="Cofnij",
                        on_action=cofnij, duration=6000)
    if hasattr(page, "open"):
        page.open(snack)
    else:
        page.overlay.append(snack)
        snack.open = True
        page.update()


# ============================================================================
#  OKNA
# ============================================================================

def _pole_licznika(auto_id, km, etykieta_pola="Stan licznika"):
    return ft.TextField(label=f"{etykieta_pola} ({jednostka_dystansu()})",
                        value=db.wartosc_pola_dystansu(km) if km else "",
                        keyboard_type=ft.KeyboardType.NUMBER, **styl_pola())


def _km_z_pola(pole, km_przy_otwarciu):
    if not (pole.value or "").strip():
        return None, None
    km = db.dystans_na_km(pole.value, calkowity=True, km_przy_otwarciu=km_przy_otwarciu)
    if not km or km <= 0:
        return None, "Podaj poprawny stan licznika"
    return km, None


def okno_zmiany_opon(page: ft.Page, state, zestaw_id, os_montazu="Wszystkie", przypomnienie_id=None, koszt=None,
                     po_zapisie=None):
    """Okno zmiany: dzień (dziś), licznik z historii licznika na ten dzień, koszt, warsztat, dopisanie
    do Serwisu, pomiar zdejmowanych. Zapis → db.zmien_opony i komunikat z „Cofnij”; `po_zapisie(wynik)`
    zamiast odświeżenia ekranu."""
    auto_id = state.auto_id
    if not auto_id or zablokowane(page, auto_id):
        return None
    dane = db.dane_opon(auto_id)
    komplet = next((k for k in dane["komplety"] if k["id"] == zestaw_id), None)
    if not komplet:
        return None
    zdejmowane = [k for k in dane["zamontowane"] if k["id"] != zestaw_id
                  and (os_montazu == "Wszystkie" or k["os"] in (os_montazu, "Wszystkie"))]
    with db.polacz_baze(zmienia_dane=False) as conn:
        z_podzespolem = db.podzespol_opon(conn, auto_id) is not None
    ostatnia = (db.wpisy_zmian_opon(auto_id) or [None])[-1]

    dzis = datetime.now().strftime("%d.%m.%Y")
    km_pocz = db.szacuj_przebieg_w_dniu(auto_id, dzis) or db.pobierz_aktualny_przebieg(auto_id) or None
    stan = {"licznik_recznie": False}
    e_przebieg = _pole_licznika(auto_id, km_pocz)
    e_przebieg.on_change = lambda e: stan.update(licznik_recznie=True)

    def po_zmianie_daty():
        km = None if stan["licznik_recznie"] else db.szacuj_przebieg_w_dniu(auto_id, e_data.value)
        if km:
            e_przebieg.value = db.wartosc_pola_dystansu(km)

    e_data = pole_daty(page, "Dzień zmiany", dzis, po_zmianie=po_zmianie_daty, podpowiedz="Wybierz")
    ostatni_koszt = (ostatnia or {}).get("cena")
    e_koszt = ft.TextField(label=f"Koszt ({symbol_waluty()})", value=liczba_do_pola(koszt) if koszt else "",
                           hint_text=f"ostatnio {formatuj_liczba(ostatni_koszt)}" if ostatni_koszt else None,
                           keyboard_type=ft.KeyboardType.NUMBER, **styl_pola())
    e_wykonawca = ft.TextField(label="Warsztat (opcjonalnie)", value=(ostatnia or {}).get("wykonawca") or "",
                               **styl_pola())
    chk_serwis = ft.Checkbox(label="Dopisz zmianę do Serwisu" if z_podzespolem else "Dopisz koszt do Innych kosztów",
                             value=True)
    chk_pomiar = ft.Checkbox(label="Zmierz zdejmowane opony po zapisie", value=False)

    tresc = []
    if opis_kompletu(komplet):
        tresc.append(podpis(opis_kompletu(komplet), max_lines=2))
    if zdejmowane:
        tresc.append(podpis("Zdejmujesz: " + ", ".join(nazwa_kompletu(k).lower() for k in zdejmowane), max_lines=2))
    if komplet.get("miejsce"):
        tresc.append(podpis(" · ".join(x for x in (f"Leżą: {komplet['miejsce']}",
                                                     f"kwit {komplet['numer_kwitu']}" if komplet.get("numer_kwitu")
                                                     else None) if x), max_lines=2))
    for ostrzezenie, kolor in ((opis_wieku(komplet["wiek"]), kolor_wieku(komplet["wiek"])),
                               (opis_bieznika_ponizej(komplet), kolor_bieznika(komplet["status_bieznika"]))):
        if ostrzezenie:
            tresc.append(podpis(ostrzezenie[:1].upper() + ostrzezenie[1:], color=kolor, max_lines=3))
    tresc += [na_cala_szerokosc(e_data), na_cala_szerokosc(e_przebieg), na_cala_szerokosc(e_koszt),
              na_cala_szerokosc(e_wykonawca), pole_wyboru(chk_serwis)]
    if zdejmowane:
        tresc.append(pole_wyboru(chk_pomiar))

    def zapisz(e):
        for kontrolka in (e_data, e_przebieg, e_koszt):
            ustaw_blad(kontrolka)
        bledy = [] if (e_data.value or "").strip() else [(e_data, "Wybierz dzień zmiany")]
        km, blad = _km_z_pola(e_przebieg, km_pocz)
        if blad:
            bledy.append((e_przebieg, blad))
        kwota = None
        if (e_koszt.value or "").strip():
            kwota = parsuj_float(e_koszt.value, None)
            if kwota is None or kwota < 0:
                bledy.append((e_koszt, "Podaj poprawny koszt"))
        if bledy:
            for kontrolka, komunikat in bledy:
                ustaw_blad(kontrolka, komunikat)
            page.update()
            return
        if km and chk_serwis.value and z_podzespolem and sprawdz_podejrzany_przebieg(
                page, e_przebieg, auto_id, km, tabela="historia", nowa_data_str=e_data.value):
            return
        wynik = db.zmien_opony(auto_id, zestaw_id, {
            "os": os_montazu, "data": e_data.value, "przebieg": km, "koszt": kwota,
            "wykonawca": e_wykonawca.value, "do_serwisu": bool(chk_serwis.value),
            "przypomnienie_id": przypomnienie_id})
        zamknij_dialog(page, dlg)
        wypchnij_w_tle(page, auto_id, "zmiana opon")
        if wynik and wynik.get("ok") and zdejmowane and chk_pomiar.value:
            state.pomiar_wstepny = {"data": wynik["data"], "przebieg": wynik["przebieg"]}
            przejdz(page, f"/magazyn/opony/{zdejmowane[0]['id']}/pomiar")
        elif po_zapisie:
            po_zapisie(wynik)
        else:
            przejdz(page, page.route)
        pokaz_komunikat_zmiany(page, wynik)

    if os_montazu == "Wszystkie":
        tytul = f"Zmiana na {komplet['sezon'].lower()}" if komplet["sezon"] else "Zmiana opon"
    else:
        tytul = f"Montaż {OSIE_SLOWAMI[os_montazu]}"
    dlg = ft.AlertDialog(
        modal=True, scrollable=True, title=ft.Text(tytul, weight="bold"),
        content=ft.Column(tresc, tight=True, spacing=SPACING["sm"]),
        actions=[ft.TextButton("Anuluj", on_click=lambda e: zamknij_dialog(page, dlg)),
                 ft.Button("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY)],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    otworz_dialog(page, dlg)
    return dlg


def okno_poczatku_montazu(page: ft.Page, state, zestaw_id, po_zapisie=None):
    """„Od kiedy na aucie?” dla zamontowanego kompletu bez okresu: dzień i licznik — podpowiedź
    z ostatniej zmiany opon tego sezonu w Serwisie."""
    auto_id = state.auto_id
    if not auto_id or zablokowane(page, auto_id):
        return None
    propozycja = db.propozycja_poczatku_montazu(auto_id, zestaw_id)
    km_pocz = propozycja["przebieg"] or (db.szacuj_przebieg_w_dniu(auto_id, propozycja["data"])
                                         if propozycja["data"] else None)
    e_przebieg = _pole_licznika(auto_id, km_pocz, "Licznik")
    stan = {"licznik_recznie": bool(propozycja["przebieg"])}
    e_przebieg.on_change = lambda e: stan.update(licznik_recznie=True)

    def po_zmianie_daty():
        km = None if stan["licznik_recznie"] else db.szacuj_przebieg_w_dniu(auto_id, e_data.value)
        if km:
            e_przebieg.value = db.wartosc_pola_dystansu(km)

    e_data = pole_daty(page, "Na aucie od", propozycja["data"] or "", po_zmianie=po_zmianie_daty, podpowiedz="Wybierz")

    def zapisz(e):
        ustaw_blad(e_data)
        ustaw_blad(e_przebieg)
        km, blad = _km_z_pola(e_przebieg, km_pocz)
        if not (e_data.value or "").strip() or blad:
            if blad:
                ustaw_blad(e_przebieg, blad)
            else:
                ustaw_blad(e_data, "Wybierz dzień założenia")
            page.update()
            return
        historia_id = propozycja["historia_id"] if e_data.value == propozycja["data"] else None
        wynik = db.ustaw_poczatek_montazu(auto_id, zestaw_id, e_data.value, km, historia_id)
        zamknij_dialog(page, dlg)
        if wynik:
            wypchnij_w_tle(page, auto_id, "sezon opon")
        if po_zapisie:
            po_zapisie(wynik)
        else:
            przejdz(page, page.route)
        pokaz_komunikat(page, "Zapisano — od tego dnia liczę kilometry kompletu." if wynik
                        else "Nie zapisano: komplet nie jest na aucie albo ma już otwarty sezon.",
                        KOLOR_STATUS["ok"] if wynik else KOLOR_STATUS["warning"])

    tresc = [podpis("Bez tego dnia nie policzę, ile kilometrów ten komplet przejechał.", max_lines=3)]
    if propozycja["data"]:
        tresc.append(podpis(f"Podpowiedź z Serwisu: zmiana opon {propozycja['data']}.", max_lines=2))
    tresc += [na_cala_szerokosc(e_data), na_cala_szerokosc(e_przebieg)]
    dlg = ft.AlertDialog(
        modal=True, scrollable=True, title=ft.Text("Od kiedy na aucie?", weight="bold"),
        content=ft.Column(tresc, tight=True, spacing=SPACING["sm"]),
        actions=[ft.TextButton("Anuluj", on_click=lambda e: zamknij_dialog(page, dlg)),
                 ft.Button("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY)],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    otworz_dialog(page, dlg)
    return dlg


def okno_okresu_montazu(page: ft.Page, state, okres, po_zmianie=None):
    """Poprawka sezonu na aucie: dzień i licznik założenia, przy zdjętym też zdjęcia; „Usuń” do kosza."""
    auto_id = state.auto_id
    if not auto_id or zablokowane(page, auto_id):
        return None
    otwarty = okres["data_zdjecia"] is None
    e_od = pole_daty(page, "Założony", okres["data"], podpowiedz="Wybierz")
    e_km_od = _pole_licznika(auto_id, okres["przebieg"], "Licznik")
    e_do = None if otwarty else pole_daty(page, "Zdjęty", okres["data_zdjecia"], podpowiedz="Wybierz")
    e_km_do = None if otwarty else _pole_licznika(auto_id, okres["przebieg_zdjecia"], "Licznik zdjęcia")
    blad_okna = ft.Text("", color=KOLOR_STATUS["error"], size=FS["caption"], visible=False)

    def odswiez(wynik=None):
        if po_zmianie:
            po_zmianie()
        else:
            przejdz(page, page.route)

    def zapisz(e):
        km_od, blad_od = _km_z_pola(e_km_od, okres["przebieg"])
        km_do, blad_do = _km_z_pola(e_km_do, okres["przebieg_zdjecia"]) if e_km_do else (None, None)
        dane = {"data": e_od.value, "przebieg": km_od, "data_zdjecia": e_do.value if e_do else None,
                "przebieg_zdjecia": km_do}
        blad = blad_od or blad_do or db.blad_okresu(dane, otwarty)
        if blad:
            blad_okna.value, blad_okna.visible = blad, True
            page.update()
            return
        zapisane = db.zapisz_okres_montazu(okres["id"], dane)
        zamknij_dialog(page, dlg)
        if zapisane:
            wypchnij_w_tle(page, auto_id, "sezon opon")
        odswiez()
        pokaz_komunikat(page, "Zapisano sezon." if zapisane else "Nie zapisano: brak uprawnień do tego auta.",
                        KOLOR_STATUS["ok"] if zapisane else KOLOR_STATUS["warning"])

    def usun(e):
        from .dialogi import pokaz_komunikat_cofnij
        wynik = db.usun_okres_z_cofnieciem(okres["id"])
        zamknij_dialog(page, dlg)
        odswiez()
        pokaz_komunikat_cofnij(page, "Usunięto sezon.", wynik)

    pola = [na_cala_szerokosc(e_od), na_cala_szerokosc(e_km_od)]
    if not otwarty:
        pola += [na_cala_szerokosc(e_do), na_cala_szerokosc(e_km_do)]
    else:
        pola.append(podpis("Komplet jest na aucie — dzień zdjęcia zapisze zmiana opon.", max_lines=2))
    dlg = ft.AlertDialog(
        modal=True, scrollable=True, title=ft.Text("Sezon na aucie", weight="bold"),
        content=ft.Column(pola + [blad_okna], tight=True, spacing=SPACING["sm"]),
        actions=[ft.TextButton("Usuń", on_click=usun, style=ft.ButtonStyle(color=KOLOR_STATUS["destructive"])),
                 ft.TextButton("Anuluj", on_click=lambda e: zamknij_dialog(page, dlg)),
                 ft.Button("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY)],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    otworz_dialog(page, dlg)
    return dlg


def tekst_terminu_zmiany(termin):
    """„zmiana: za 152 dni” z dnia przypomnienia (date) albo None."""
    if not termin:
        return None
    _, tekst = kolor_i_tekst_terminu(termin.strftime("%d.%m.%Y"))
    return tekst or termin.strftime("%d.%m.%Y")


__all__ = [
    "NAZWY_KOL",
    "OSIE_SLOWAMI",
    "ROLE_BIEZNIKA",
    "ROLE_WIEKU",
    "chip_kompletu",
    "ikona_sezonu",
    "kandydat_zmiany",
    "kolor_bieznika",
    "kolor_wieku",
    "komunikat_zmiany",
    "linijka_kompletu",
    "nazwa_kompletu",
    "okno_okresu_montazu",
    "okno_poczatku_montazu",
    "okno_zmiany_opon",
    "opis_bieznika_ponizej",
    "opis_kompletu",
    "opis_wieku",
    "pasek_bieznika",
    "pokaz_komunikat_zmiany",
    "schemat_kol",
    "stan_kompletu",
    "tekst_terminu_zmiany",
    "tekst_zakresu_bieznika",
    "wskazowka_osi",
]
