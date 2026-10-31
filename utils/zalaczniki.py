"""Załączniki i zdjęcia: wybór, podgląd, wskaźniki."""

import db
import flet as ft
import log
import os
import pathlib
from contextlib import contextmanager

from .stale import FS, KOLOR_STATUS, RADIUS, SPACING
from .typografia import podpis
from .wyglad import powierzchnia
from .dialogi import otworz_dialog, otworz_dno, pokaz_komunikat, zamknij_dialog, zamknij_dno
from .formularze import styl_pola


ROZSZERZENIA_ZALACZNIKOW = ["jpg", "jpeg", "png", "webp", "pdf"]

# Ikony rodzajów plików wpisu (db.RODZAJE_ZALACZNIKOW) i strony dokumentu ze skarbca.
IKONY_RODZAJOW_ZALACZNIKA = {
    "paragon": ft.Icons.RECEIPT_LONG,
    "faktura": ft.Icons.REQUEST_QUOTE,
    "gwarancja": ft.Icons.VERIFIED_USER,
    "zdjecie_czesci": ft.Icons.SETTINGS_SUGGEST,
    "zdjecie": ft.Icons.PHOTO_CAMERA,
    "inne": ft.Icons.ATTACH_FILE,
    db.TYP_PLIKU_DOKUMENTU: ft.Icons.DESCRIPTION,
}


def etykieta_rodzaju_pliku(typ) -> str:
    if typ == db.TYP_PLIKU_DOKUMENTU:
        return "Strona dokumentu"
    return db.RODZAJE_ZALACZNIKOW.get(typ) or "Plik"


def abs_zalacznik(sciezka_wzgledna):
    """Bezwzględna ścieżka załącznika dla ft.Image przez db.sciezka_pliku_zalacznika
    (postać względna, dawna bezwzględna, plik z innego urządzenia — szuka w załącznikach
    i koszu). Nie znaleziony — ścieżka z bazy (komunikat mówi, co tam stoi)."""
    if not sciezka_wzgledna:
        return None
    return os.path.abspath(db.sciezka_pliku_zalacznika(sciezka_wzgledna))


def komponent_zalacznika(page: ft.Page, sciezka_zapisana=None, auto_id=None):
    """Jeden plik (zdjęcie pojazdu, zdjęcie karoserii): podgląd, wybór, usunięcie. Zwraca
    (kontrolka, pobierz_wynik) — wynik dla db.przygotuj_nowy_zalacznik. `auto_id` dokłada
    „Z zapisanych zdjęć”; po zapisie formularz woła db.zamknij_szkice_po_kopii."""
    stan = {"nowa_sciezka": None, "usuniete": False, "szkic_id": None}

    def zawartosc_podgladu(sciezka):
        if sciezka:
            if sciezka.lower().endswith(".pdf"):
                return ft.Icon(ft.Icons.PICTURE_AS_PDF, size=32, color=ft.Colors.RED_700)  # paleta: tożsamość — PDF ma swój kolor niezależnie od stanu
            return ft.Image(src=sciezka, width=56, height=56, fit="cover", border_radius=10)
        return ft.Icon(ft.Icons.IMAGE_OUTLINED, size=26, color=ft.Colors.ON_SURFACE_VARIANT)

    ramka_podgladu = ft.Container(
        width=56, height=56, alignment=ft.Alignment.CENTER,
        **powierzchnia(page, "blok"),
        content=zawartosc_podgladu(abs_zalacznik(sciezka_zapisana))
    )
    tekst_nazwy = ft.Text(
        os.path.basename(sciezka_zapisana) if sciezka_zapisana else "Brak załącznika",
        size=13, color=ft.Colors.ON_SURFACE_VARIANT, expand=True
    )
    btn_usun = ft.IconButton(
        icon=ft.Icons.DELETE_OUTLINE, icon_color=KOLOR_STATUS["destructive"],
        tooltip="Usuń załącznik", visible=bool(sciezka_zapisana)
    )

    def odswiez(sciezka_podgladu, etykieta, pokazuj_usun):
        ramka_podgladu.content = zawartosc_podgladu(sciezka_podgladu)
        tekst_nazwy.value = etykieta
        btn_usun.visible = pokazuj_usun
        wolne = ile_zapisanych - (1 if stan["szkic_id"] else 0)
        btn_zapisane.visible, btn_zapisane.content = wolne > 0, f"Z zapisanych zdjęć ({wolne})"
        try:
            page.update()
        except Exception:
            log.polkniety("odświeżenie podglądu załącznika")

    def _obsluz_wybrane(pliki):
        if not pliki:
            return
        sciezki = [p.path for p in pliki if getattr(p, "path", None)]
        if not sciezki:
            pokaz_komunikat(page, "Brak dostępu do ścieżki (Uprawnienia telefonu).", KOLOR_STATUS["error"])
            return
        stan.update(nowa_sciezka=sciezki[0], usuniete=False, szkic_id=None)
        odswiez(sciezki[0], os.path.basename(sciezki[0]), True)

    def _po_wyborze_zapisanego(szkice):
        s = szkice[0]
        stan.update(nowa_sciezka=abs_zalacznik(s["zalacznik"]), usuniete=False, szkic_id=s["id"])
        odswiez(stan["nowa_sciezka"], f"Zapisane zdjęcie z {s['data']}", True)

    def z_zapisanych(e):
        pokaz_zapisane_zdjecia(page, auto_id, _po_wyborze_zapisanego, pominiete={stan["szkic_id"]}, wiele=False,
                               opis="Formularz dostanie kopię zdjęcia, a po zapisie zniknie ono z „Do wpisania”.")

    async def wybierz(e):
        try:
            _obsluz_wybrane(await page.zalacznik_picker.pick_files(
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=ROZSZERZENIA_ZALACZNIKOW,
                allow_multiple=False
            ))
        except Exception as ex:
            pokaz_komunikat(page, f"Błąd wczytywania pliku: {ex}", KOLOR_STATUS["error"])

    def usun(e):
        stan.update(nowa_sciezka=None, usuniete=True, szkic_id=None)
        odswiez(None, "Brak załącznika", False)

    btn_usun.on_click = usun

    wiersz = ft.Row([ramka_podgladu, tekst_nazwy, btn_usun], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=10)
    btn_wybierz = ft.TextButton("Dodaj / zmień załącznik (zdjęcie, PDF)", icon=ft.Icons.ATTACH_FILE, on_click=wybierz)
    ile_zapisanych = len(db.szkice_ze_zdjeciem(auto_id)) if auto_id else 0
    btn_zapisane = ft.TextButton(f"Z zapisanych zdjęć ({ile_zapisanych})", icon=ft.Icons.PHOTO_LIBRARY,
                                 on_click=z_zapisanych, visible=bool(ile_zapisanych))

    kontener = ft.Column([wiersz, btn_wybierz, btn_zapisane], spacing=8)

    def pobierz_wynik():
        if stan["usuniete"]:
            return ""
        if stan["nowa_sciezka"]:
            return stan["nowa_sciezka"]
        return None

    return kontener, pobierz_wynik


# Siatka wybranych zdjęć w formularzu: 3 miniatury w rzędzie na telefonie.
KOLUMNY_MINIATUR = {"xs": 4, "sm": 3, "md": 2}


def komponent_wielu_nowych_zdjec(page: ft.Page, auto_id=None):
    """MASOWE dodawanie nowych zdjęć (karoseria), w kilku turach — nowe dopisują się do siatki
    miniatur, kafel „Dodaj” stoi na jej początku. Zwraca (kontrolka, pobierz_wynik) — ścieżki
    źródłowe; kopiowanie dopiero przy zapisie formularza. `auto_id` dokłada kafel „Zapisane”
    (kolejka „Do wpisania”); po zapisie formularz woła db.zamknij_szkice_po_kopii."""
    stan = {"pliki": [], "szkice": {}}
    zapisane = db.szkice_ze_zdjeciem(auto_id) if auto_id else []
    siatka = ft.ResponsiveRow(spacing=SPACING["sm"], run_spacing=SPACING["sm"])
    licznik = podpis("Nie wybrano jeszcze żadnego zdjęcia.")

    def usun(sciezka):
        stan["pliki"] = [s for s in stan["pliki"] if s != sciezka]
        stan["szkice"].pop(sciezka, None)
        odswiez()

    def wolne_zapisane():
        return [s for s in zapisane if s["id"] not in stan["szkice"].values()]

    def dodaj_zapisane(szkice):
        for s in szkice:
            sciezka = abs_zalacznik(s["zalacznik"])
            if sciezka not in stan["pliki"]:
                stan["pliki"].append(sciezka)
            stan["szkice"][sciezka] = s["id"]
        odswiez()

    def z_zapisanych(e):
        pokaz_zapisane_zdjecia(page, auto_id, dodaj_zapisane, pominiete=set(stan["szkice"].values()),
                               opis="Galeria dostanie kopie zdjęć, a po zapisie znikną one z „Do wpisania”.")

    def miniatura(sciezka):
        return ft.Container(
            col=KOLUMNY_MINIATUR, aspect_ratio=1, border_radius=RADIUS["md"], clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            bgcolor=powierzchnia(page, "blok")["bgcolor"],
            content=ft.Stack([
                ft.Container(left=0, top=0, right=0, bottom=0, content=ft.Image(
                    src=sciezka, fit=ft.BoxFit.COVER, cache_width=320, gapless_playback=True,
                    semantics_label=os.path.basename(sciezka))),
                ft.Container(right=0, top=0, content=ft.IconButton(
                    icon=ft.Icons.CLOSE, icon_size=16, icon_color=ft.Colors.WHITE,
                    bgcolor=ft.Colors.with_opacity(0.45, ft.Colors.BLACK), tooltip="Usuń z wybranych",
                    on_click=lambda e, s=sciezka: usun(s))),
            ]),
        )

    def kafel_dodaj():
        return ft.Container(
            col=KOLUMNY_MINIATUR, aspect_ratio=1, border_radius=RADIUS["md"], ink=True, on_click=wybierz,
            border=ft.Border.all(1.5, ft.Colors.with_opacity(0.45, ft.Colors.PRIMARY)),
            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.PRIMARY), alignment=ft.Alignment.CENTER,
            tooltip="Wybierz zdjęcia — można zaznaczyć od razu kilka",
            content=ft.Column([
                ft.Icon(ft.Icons.ADD_PHOTO_ALTERNATE, size=26, color=ft.Colors.PRIMARY),
                ft.Text("Dodaj", size=FS["label"], weight="bold", color=ft.Colors.PRIMARY),
            ], spacing=2, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        )

    def kafel_zapisane(ile):
        return ft.Container(
            col=KOLUMNY_MINIATUR, aspect_ratio=1, border_radius=RADIUS["md"], ink=True, on_click=z_zapisanych,
            border=ft.Border.all(1.5, ft.Colors.with_opacity(0.45, ft.Colors.PRIMARY)),
            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.PRIMARY), alignment=ft.Alignment.CENTER,
            tooltip="Zdjęcia z kolejki „Do wpisania”",
            content=ft.Column([
                ft.Icon(ft.Icons.PHOTO_LIBRARY, size=26, color=ft.Colors.PRIMARY),
                ft.Text(f"Zapisane ({ile})", size=FS["label"], weight="bold", color=ft.Colors.PRIMARY),
            ], spacing=2, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        )

    def odswiez(z_aktualizacja=True):
        wolne = len(wolne_zapisane())
        siatka.controls = ([kafel_dodaj()] + ([kafel_zapisane(wolne)] if wolne else [])
                           + [miniatura(s) for s in stan["pliki"]])
        n = len(stan["pliki"])
        licznik.value = ("Nie wybrano jeszcze żadnego zdjęcia." if n == 0
                         else f"Wybrane: {db.liczba_z_odmiana(n, 'zdjęcie', 'zdjęcia', 'zdjęć')}")
        if not z_aktualizacja:
            return
        try:
            siatka.update()
            licznik.update()
        except Exception:
            log.polkniety("odświeżenie listy wybranych zdjęć")

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
            pokaz_komunikat(page, "Pliki PDF pominięto — galeria karoserii przyjmuje tylko zdjęcia.", KOLOR_STATUS["warning"])
        elif not nowe:
            pokaz_komunikat(page, "Brak dostępu do wybranych plików (uprawnienia).", KOLOR_STATUS["error"])

    async def wybierz(e):
        try:
            dodaj_pliki(await page.zalacznik_picker.pick_files(
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["jpg", "jpeg", "png", "webp"],
                allow_multiple=True,
            ))
        except Exception as ex:
            pokaz_komunikat(page, f"Błąd wczytywania plików: {ex}", KOLOR_STATUS["error"])

    odswiez(z_aktualizacja=False)
    kontener = ft.Column([siatka, licznik], spacing=8)
    return kontener, lambda: list(stan["pliki"])


async def udostepnij_pliki(page: ft.Page, sciezki):
    """Systemowe „Udostępnij” dla plików (PDF, komplet stron dokumentu) — zamiast surowego
    `file://`, które Android (FileUriExposedException) i iOS blokują. Bez usługi Share
    (komputer) otwiera pierwszy plik."""
    sciezki = [s for s in sciezki or [] if s and os.path.exists(s)]
    if not sciezki:
        pokaz_komunikat(page, "Pliku nie ma na tym urządzeniu.", KOLOR_STATUS["error"])
        return
    serwis = getattr(page, "share_service", None)
    if serwis is not None:
        try:
            await serwis.share_files([ft.ShareFile.from_path(s) for s in sciezki])
            return
        except Exception:
            log.polkniety("udostępnianie plików przez system")
    try:
        await ft.UrlLauncher().launch_url(pathlib.Path(sciezki[0]).as_uri())
    except Exception:
        pokaz_komunikat(page, "Nie można otworzyć pliku na tym urządzeniu.", KOLOR_STATUS["error"])


def pokaz_podglad_zalacznika(page: ft.Page, sciezka_wzgledna, tytul="Załącznik"):
    """PDF idzie do systemowego „Udostępnij”, zdjęcie — pełny ekran z przybliżaniem."""
    if not sciezka_wzgledna:
        return

    abs_path = abs_zalacznik(sciezka_wzgledna)
    if abs_path.lower().endswith(".pdf"):
        async def otworz_pdf():
            await udostepnij_pliki(page, [abs_path])

        page.run_task(otworz_pdf)
        return

    # 2. Pełnoekranowy podgląd zdjęcia z możliwością przybliżania (pinch-to-zoom)
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


def _sciezka_podgladu(pozycja):
    """Plik do pokazania: świeżo wybrany — tam, skąd przyszedł; zapisany — przez abs_zalacznik."""
    return pozycja["sciezka"] if pozycja.get("nowy") else abs_zalacznik(pozycja["sciezka"])


def miniatura_zalacznika(page: ft.Page, sciezka, rozmiar=56, on_click=None, tooltip=None):
    """Kwadrat z podglądem zdjęcia albo ikoną PDF; `sciezka` bezwzględna."""
    if sciezka and db.czy_pdf(sciezka):
        tresc = ft.Icon(ft.Icons.PICTURE_AS_PDF, size=rozmiar // 2, color=ft.Colors.RED_700)  # paleta: tożsamość — PDF ma swój kolor niezależnie od stanu
    elif sciezka:
        tresc = ft.Image(src=sciezka, width=rozmiar, height=rozmiar, fit="cover", border_radius=RADIUS["sm"])
    else:
        tresc = ft.Icon(ft.Icons.IMAGE_OUTLINED, size=rozmiar // 2, color=ft.Colors.ON_SURFACE_VARIANT)
    return ft.Container(width=rozmiar, height=rozmiar, alignment=ft.Alignment.CENTER, **powierzchnia(page, "blok"),
                        content=tresc, on_click=on_click, ink=on_click is not None, tooltip=tooltip)


def pokaz_zalaczniki(page: ft.Page, zalaczniki, tytul="Załączniki"):
    """Jeden plik — od razu podgląd; kilka — lista z miniaturą, rodzajem i opisem, plus
    „Udostępnij wszystkie”."""
    pliki = [z for z in zalaczniki or [] if z.get("sciezka")]
    if len(pliki) == 1:
        pokaz_podglad_zalacznika(page, pliki[0]["sciezka"], tytul)
    if len(pliki) <= 1:
        return
    bs = ft.BottomSheet(ft.Container(padding=20, bgcolor=ft.Colors.SURFACE))

    def otworz(z):
        def handler(e):
            zamknij_dno(page, bs)
            pokaz_podglad_zalacznika(page, z["sciezka"], tytul)
        return handler

    async def udostepnij(e):
        zamknij_dno(page, bs)
        await udostepnij_pliki(page, [abs_zalacznik(z["sciezka"]) for z in pliki])

    wiersze = [ft.Text(tytul, weight="bold", size=FS["heading"], color=ft.Colors.PRIMARY), ft.Divider()]
    for z in pliki:
        wiersze.append(ft.ListTile(
            leading=miniatura_zalacznika(page, abs_zalacznik(z["sciezka"]), 44),
            title=ft.Text(etykieta_rodzaju_pliku(z.get("typ"))),
            subtitle=podpis(z["opis"]) if z.get("opis") else None,
            on_click=otworz(z),
        ))
    wiersze.append(ft.TextButton("Udostępnij wszystkie", icon=ft.Icons.SHARE, on_click=udostepnij))
    bs.content.content = ft.Column(wiersze, tight=True)
    otworz_dno(page, bs)


def pokaz_zapisane_zdjecia(page: ft.Page, auto_id, po_wyborze, pominiete=(), wiele=True, opis=None):
    """Arkusz „Zapisane zdjęcia” — kolejka „Do wpisania” pojazdu, najnowsze pierwsze. Dotknięcie
    zaznacza (`wiele=False` — od razu wybiera), przytrzymanie powiększa; `po_wyborze(szkice)`."""
    szkice = list(reversed(db.szkice_ze_zdjeciem(auto_id, pominiete))) if auto_id else []
    if not szkice:
        pokaz_komunikat(page, "W „Do wpisania” nie ma zdjęć do wybrania.")
        return
    wybrane = []
    bs = ft.BottomSheet(ft.Container(padding=ft.Padding(16, 16, 16, 8), bgcolor=ft.Colors.SURFACE))
    siatka = ft.ResponsiveRow(spacing=SPACING["sm"], run_spacing=SPACING["sm"])
    przycisk = ft.Button("Dodaj", icon=ft.Icons.CHECK, disabled=True)

    def zakoncz(lista):
        zamknij_dno(page, bs)
        po_wyborze(lista)

    def dotknij(s):
        if not wiele:
            return zakoncz([s])
        if s["id"] in wybrane:
            wybrane.remove(s["id"])
        else:
            wybrane.append(s["id"])
        odswiez()

    def kafel(s):
        zaznaczony = s["id"] in wybrane
        warstwy = [ft.Container(left=0, top=0, right=0, bottom=0, content=ft.Image(
            src=abs_zalacznik(s["zalacznik"]), fit=ft.BoxFit.COVER, cache_width=320, gapless_playback=True,
            semantics_label=f"Zdjęcie z {s['data']}"))]
        if zaznaczony:
            warstwy.append(ft.Container(right=6, top=6, content=ft.Icon(ft.Icons.CHECK_CIRCLE, size=24,
                                                                        color=ft.Colors.PRIMARY)))
        return ft.Container(
            col=KOLUMNY_MINIATUR, border_radius=RADIUS["md"], ink=True, on_click=lambda e: dotknij(s),
            on_long_press=lambda e: pokaz_podglad_zalacznika(page, s["zalacznik"], "Zapisane zdjęcie"),
            content=ft.Column([
                ft.Container(aspect_ratio=1, border_radius=RADIUS["md"], clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                             bgcolor=powierzchnia(page, "blok")["bgcolor"],
                             border=ft.Border.all(3, ft.Colors.PRIMARY) if zaznaczony else None,
                             content=ft.Stack(warstwy)),
                podpis(s["data"]),
            ], spacing=4, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        )

    def odswiez(z_aktualizacja=True):
        siatka.controls = [kafel(s) for s in szkice]
        przycisk.disabled = not wybrane
        przycisk.content = f"Dodaj ({len(wybrane)})" if wybrane else "Dodaj"
        if z_aktualizacja:
            try:
                bs.content.content.update()
            except RuntimeError:
                log.polkniety("odświeżenie wyboru zapisanych zdjęć")

    przycisk.on_click = lambda e: zakoncz([s for s in szkice if s["id"] in wybrane])
    akcje = [ft.TextButton("Anuluj", on_click=lambda e: zamknij_dno(page, bs))] + ([przycisk] if wiele else [])
    odswiez(z_aktualizacja=False)
    bs.content.content = ft.Column([
        ft.Text("Zapisane zdjęcia", weight="bold", size=FS["heading"], color=ft.Colors.PRIMARY),
        podpis(opis or "Zdjęcia z kolejki „Do wpisania”.", max_lines=3),
        podpis("Dotknij, żeby " + ("zaznaczyć" if wiele else "wybrać") + " · przytrzymaj, żeby powiększyć.",
               max_lines=2),
        siatka,
        ft.Row(akcje, alignment=ft.MainAxisAlignment.END),
    ], tight=True, spacing=SPACING["sm"])
    otworz_dno(page, bs)


def wskaznik_zalacznikow(page: ft.Page, zalaczniki, tytul="Załącznik"):
    """Plakietka na karcie listy: ikona i liczba plików; dotknięcie otwiera podgląd."""
    pliki = [z for z in zalaczniki or [] if z.get("sciezka")]
    if not pliki:
        return ft.Container(width=0, height=0)
    sam_pdf = all(db.czy_pdf(z["sciezka"]) for z in pliki)
    kolor = ft.Colors.RED_700 if sam_pdf else ft.Colors.PRIMARY  # paleta: tożsamość — PDF ma swój kolor niezależnie od stanu
    ikona = ft.Icons.PICTURE_AS_PDF if sam_pdf else ft.Icons.IMAGE if len(pliki) == 1 else ft.Icons.ATTACH_FILE
    tresc = [ft.Icon(ikona, size=15, color=kolor)]
    if len(pliki) > 1:
        tresc.append(ft.Text(str(len(pliki)), size=FS["caption"], weight="bold", color=kolor))
    return ft.Container(
        height=28, padding=ft.Padding(6, 0, 6, 0), border_radius=8,
        bgcolor=ft.Colors.with_opacity(0.12, kolor), alignment=ft.Alignment.CENTER,
        tooltip="Pokaż plik" if len(pliki) == 1 else "Pokaż pliki",
        content=ft.Row(tresc, spacing=2, tight=True),
        on_click=lambda e: pokaz_zalaczniki(page, pliki, tytul),
    )


async def szybkie_dodanie_zalacznikow(page: ft.Page, tabela, rekord_id, po_zapisie):
    """„Dodaj plik” z menu karty: wybrane zdjęcia i PDF-y dopisują się na koniec wpisu."""

    def zapisz(pliki):
        if not pliki:
            return
        sciezki = [p.path for p in pliki if getattr(p, "path", None)]
        if not sciezki:
            pokaz_komunikat(page, "Brak dostępu do pliku (uprawnienia).", KOLOR_STATUS["error"])
            return
        ile = db.dodaj_zalaczniki(tabela, rekord_id, sciezki)
        if not ile:
            pokaz_komunikat(page, "Nie udało się zapisać pliku.", KOLOR_STATUS["error"])
            return
        pokaz_komunikat(page, f"Dodano {db.liczba_z_odmiana(ile, 'plik', 'pliki', 'plików')}.")
        po_zapisie()

    try:
        zapisz(await page.zalacznik_picker.pick_files(
            file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=ROZSZERZENIA_ZALACZNIKOW, allow_multiple=True))
    except Exception as ex:
        pokaz_komunikat(page, f"Błąd wczytywania: {ex}", KOLOR_STATUS["error"])


def pozycje_menu_zalacznikow(page: ft.Page, tabela, rekord_id, zalaczniki, tytul, po_zapisie):
    """„Pokaż pliki” (wolno też w podglądzie) i „Dodaj plik” do menu karty listy."""
    async def dodaj():
        await szybkie_dodanie_zalacznikow(page, tabela, rekord_id, po_zapisie)

    pozycje = []
    if zalaczniki:
        ile = len(zalaczniki)
        pozycje.append({"ikona": ft.Icons.ATTACH_FILE, "tekst": "Pokaż plik" if ile == 1 else f"Pokaż pliki ({ile})",
                        "czyta": True, "akcja": lambda: pokaz_zalaczniki(page, zalaczniki, tytul)})
    pozycje.append({"ikona": ft.Icons.ADD_A_PHOTO, "tekst": "Dodaj plik (zdjęcie, PDF)", "akcja": dodaj})

    # Zdjęcia z kolejki „Do wpisania” auta tego wpisu — dopisują się od razu, bez kopii.
    auto_id = db.auto_id_rekordu(tabela, rekord_id)
    ile = len(db.szkice_ze_zdjeciem(auto_id)) if auto_id else 0

    def po_wyborze(szkice):
        dodane = db.dolacz_szkice_do_wpisu(tabela, rekord_id, [s["id"] for s in szkice])
        if not dodane:
            pokaz_komunikat(page, "Nie udało się dodać zdjęć.", KOLOR_STATUS["error"])
            return
        pokaz_komunikat(page, f"Dodano {db.liczba_z_odmiana(dodane, 'zdjęcie', 'zdjęcia', 'zdjęć')} z „Do wpisania”.")
        po_zapisie()

    if ile:
        pozycje.append({"ikona": ft.Icons.PHOTO_LIBRARY, "tekst": f"Dodaj z zapisanych zdjęć ({ile})",
                        "akcja": lambda: pokaz_zapisane_zdjecia(
                            page, auto_id, po_wyborze,
                            opis="Wybrane zdjęcia od razu dopiszą się do wpisu i znikną z „Do wpisania”.")})
    return pozycje


class PolaZalacznikow:
    """Pliki wpisu w formularzu: miniatura, rodzaj (paragon, faktura…), opis, kolejność.
    Kopie robi dopiero `zapis()`; pliki usuniętych pozycji znikają po udanym zapisie.
    Formularz: `kontrolka`, `migawka()`, `with pola.zapis(): … pola.zapisz_w(conn, id, auto_id)`.
    `dokument=True` — strony dokumentu ze skarbca, bez wyboru rodzaju. `auto_id` — przycisk
    „Z zapisanych zdjęć”: zdjęcie przechodzi bez kopii, a szkic zamyka `zapisz_w`."""

    def __init__(self, page: ft.Page, tabela, rekord_id=None, szkic=None, dokument=False, auto_id=None):
        self._page = page
        self.tabela = tabela
        self.dokument = dokument
        self.pozycje = [{"id": z["id"], "sciezka": z["sciezka"], "nowy": False, "typ": z["typ"],
                         "opis": z["opis"] or ""} for z in db.pobierz_zalaczniki(tabela, rekord_id)]
        # Zdjęcie szkicu przechodzi na wpis bez kopiowania; usunięte tutaj znika po zapisie.
        if szkic and szkic.get("zalacznik"):
            self.pozycje.append({"id": None, "sciezka": szkic["zalacznik"], "nowy": False,
                                 "typ": "paragon", "opis": ""})
        self._usuniete_bez_wiersza = []
        self._kopie = {}
        self._do_skasowania = []
        self._zapisano = False
        self._lista = ft.Column(spacing=SPACING["sm"])
        tekst = ("Dodaj strony (zdjęcia, PDF — można kilka naraz)" if dokument
                 else "Dodaj pliki (zdjęcia, PDF — można kilka naraz)")
        # Kolejka „Do wpisania” auta — bez szkicu, z którego formularz powstał.
        self.auto_id = auto_id
        self._wlasny_szkic = szkic.get("id") if szkic else None
        self._zapisane = db.szkice_ze_zdjeciem(auto_id, {self._wlasny_szkic}) if auto_id else []
        self._przycisk_zapisanych = ft.TextButton(icon=ft.Icons.PHOTO_LIBRARY, on_click=self._z_zapisanych)
        self.kontrolka = ft.Column([
            self._lista, ft.TextButton(tekst, icon=ft.Icons.ATTACH_FILE, on_click=self._wybierz),
            self._przycisk_zapisanych,
        ], spacing=SPACING["sm"])
        self._odswiez(aktualizuj=False)

    def migawka(self):
        return tuple((p["id"], p["sciezka"], p["typ"], p["opis"]) for p in self.pozycje)

    # ---------------------------------------------------------------- wygląd

    def _odswiez(self, aktualizuj=True):
        if self.pozycje:
            self._lista.controls = [self._wiersz(i, p) for i, p in enumerate(self.pozycje)]
        else:
            self._lista.controls = [podpis("Brak plików — dodaj zdjęcia stron albo PDF." if self.dokument
                                           else "Brak plików — paragon, faktura albo zdjęcie wymienionej części.")]
        wolne = len([s for s in self._zapisane if s["id"] not in self._szkice_w_pozycjach()])
        self._przycisk_zapisanych.visible = bool(wolne)
        self._przycisk_zapisanych.content = f"Z zapisanych zdjęć ({wolne})"
        if aktualizuj:
            try:
                self.kontrolka.update()
            except Exception:
                log.polkniety("odświeżenie listy plików w formularzu")

    def _wybor_rodzaju(self, p):
        def ustaw(typ):
            def handler(e):
                p["typ"] = typ
                self._odswiez()
            return handler

        chip = ft.Container(
            padding=ft.Padding(10, 4, 6, 4), border_radius=RADIUS["pill"],
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            content=ft.Row([
                ft.Icon(IKONY_RODZAJOW_ZALACZNIKA.get(p["typ"], ft.Icons.ATTACH_FILE), size=14, color=ft.Colors.PRIMARY),
                ft.Text(etykieta_rodzaju_pliku(p["typ"]), size=FS["label"]),
                ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=16, color=ft.Colors.ON_SURFACE_VARIANT),
            ], spacing=4, tight=True),
        )
        return ft.PopupMenuButton(content=chip, tooltip="Rodzaj pliku", items=[
            ft.PopupMenuItem(content=ft.Row([ft.Icon(IKONY_RODZAJOW_ZALACZNIKA[k], size=16), ft.Text(e)], spacing=8),
                             on_click=ustaw(k))
            for k, e in db.RODZAJE_ZALACZNIKOW.items()
        ])

    def _wiersz(self, i, p):
        def zmien_opis(e):
            p["opis"] = e.control.value or ""

        opis = ft.TextField(value=p["opis"], hint_text="Opis (opcjonalnie)", dense=True, text_size=FS["body"],
                            on_change=zmien_opis,
                            **{**styl_pola(page=self._page), "content_padding": ft.Padding(12, 8, 12, 8)})
        prawa = [opis] if self.dokument else [self._wybor_rodzaju(p), opis]
        przyciski = []
        if i > 0:
            przyciski.append(ft.IconButton(ft.Icons.ARROW_UPWARD, icon_size=18, tooltip="Przesuń wyżej",
                                           on_click=lambda e: self._przesun(i)))
        przyciski.append(ft.IconButton(ft.Icons.CLOSE, icon_size=18, icon_color=KOLOR_STATUS["destructive"],
                                       tooltip="Usuń plik", on_click=lambda e: self._usun(i)))
        return ft.Row([
            miniatura_zalacznika(self._page, _sciezka_podgladu(p), 56, tooltip="Powiększ",
                                 on_click=lambda e: pokaz_podglad_zalacznika(self._page, _sciezka_podgladu(p), "Plik")),
            ft.Column(prawa, spacing=6, expand=True),
            ft.Column(przyciski, spacing=0, tight=True),
        ], spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.START)

    # ---------------------------------------------------------------- zmiany

    def _przesun(self, i):
        if 0 < i < len(self.pozycje):
            self.pozycje[i - 1], self.pozycje[i] = self.pozycje[i], self.pozycje[i - 1]
            self._odswiez()

    def _usun(self, i):
        p = self.pozycje.pop(i)
        # Zdjęcie z kolejki wraca do niej nietknięte; zdjęcie szkicu formularza znika po zapisie.
        if p["id"] is None and not p["nowy"] and not p.get("szkic_id"):
            self._usuniete_bez_wiersza.append(p["sciezka"])
        self._odswiez()

    def _szkice_w_pozycjach(self):
        return {p["szkic_id"] for p in self.pozycje if p.get("szkic_id")}

    def _z_zapisanych(self, e=None):
        pokaz_zapisane_zdjecia(self._page, self.auto_id, self.dodaj_szkice,
                               pominiete={self._wlasny_szkic, *self._szkice_w_pozycjach()},
                               opis="Zdjęcie przejdzie do tego wpisu i po zapisie zniknie z „Do wpisania”.")

    def dodaj_szkice(self, szkice):
        """Zdjęcia z kolejki „Do wpisania” — bez kopii; szkic zamyka dopiero zapis wpisu."""
        juz = self._szkice_w_pozycjach() | {self._wlasny_szkic}
        for s in szkice:
            if s["id"] in juz or not s.get("zalacznik"):
                continue
            typ = (db.TYP_PLIKU_DOKUMENTU if self.dokument
                   else db.typ_dla_pliku(s["zalacznik"], [p["typ"] for p in self.pozycje]))
            self.pozycje.append({"id": None, "sciezka": s["zalacznik"], "nowy": False, "typ": typ,
                                 "opis": s.get("opis") or "", "szkic_id": s["id"]})
            juz.add(s["id"])
        self._odswiez()

    def dodaj_pliki(self, sciezki):
        """Dopisuje wybrane pliki (ścieżki źródłowe) z podpowiedzią rodzaju."""
        for sciezka in sciezki:
            if any(p["nowy"] and p["sciezka"] == sciezka for p in self.pozycje):
                continue
            typ = db.TYP_PLIKU_DOKUMENTU if self.dokument else db.typ_dla_pliku(sciezka, [p["typ"] for p in self.pozycje])
            self.pozycje.append({"id": None, "sciezka": sciezka, "nowy": True, "typ": typ, "opis": ""})
        self._odswiez()

    def _po_wyborze(self, pliki):
        if not pliki:
            return
        sciezki = [p.path for p in pliki if getattr(p, "path", None)]
        if not sciezki:
            pokaz_komunikat(self._page, "Brak dostępu do pliku (uprawnienia telefonu).", KOLOR_STATUS["error"])
            return
        self.dodaj_pliki(sciezki)

    async def _wybierz(self, e):
        try:
            self._po_wyborze(await self._page.zalacznik_picker.pick_files(
                file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=ROZSZERZENIA_ZALACZNIKOW,
                allow_multiple=True))
        except Exception as ex:
            pokaz_komunikat(self._page, f"Błąd wczytywania pliku: {ex}", KOLOR_STATUS["error"])

    # ---------------------------------------------------------------- zapis

    @contextmanager
    def zapis(self):
        """Kopiuje nowe pliki do folderu aplikacji. Błąd w bloku albo brak `zapisz_w` sprząta
        kopie; po udanym zapisie z dysku znikają pliki usuniętych pozycji."""
        self._kopie = {}
        for p in self.pozycje:
            if p["nowy"]:
                zapisana = db.zapisz_zalacznik(p["sciezka"])
                if zapisana:
                    self._kopie[id(p)] = zapisana
        self._do_skasowania = []
        self._zapisano = False
        try:
            yield self
        except BaseException:
            self._anuluj_kopie()
            raise
        if not self._zapisano:
            self._anuluj_kopie()
            return
        for sciezka in self._do_skasowania:
            db.usun_plik_zalacznika(sciezka)

    def _anuluj_kopie(self):
        for zapisana in self._kopie.values():
            db.usun_plik_zalacznika(zapisana)
        self._kopie = {}

    def zapisz_w(self, conn, rekord_id, auto_id):
        """Pliki wpisu w transakcji formularza — wewnątrz `zapis()`."""
        pozycje = []
        for p in self.pozycje:
            if p.get("szkic_id"):
                # Szkic zamyka się w tej transakcji; zniknął w międzyczasie (kosz) — zdjęcia już nie ma.
                sciezka = db.przejmij_szkic(conn, p["szkic_id"], auto_id)
            else:
                sciezka = self._kopie.get(id(p)) if p["nowy"] else p["sciezka"]
            if sciezka:
                pozycje.append({"id": p["id"], "sciezka": sciezka, "typ": p["typ"], "opis": p["opis"]})
        self._do_skasowania = (db.zapisz_zalaczniki_rekordu(conn, self.tabela, rekord_id, auto_id, pozycje)
                               + list(self._usuniete_bez_wiersza))
        self._zapisano = True


__all__ = [
    "IKONY_RODZAJOW_ZALACZNIKA",
    "PolaZalacznikow",
    "ROZSZERZENIA_ZALACZNIKOW",
    "abs_zalacznik",
    "etykieta_rodzaju_pliku",
    "KOLUMNY_MINIATUR",
    "komponent_wielu_nowych_zdjec",
    "komponent_zalacznika",
    "miniatura_zalacznika",
    "pokaz_podglad_zalacznika",
    "pokaz_zalaczniki",
    "pokaz_zapisane_zdjecia",
    "pozycje_menu_zalacznikow",
    "szybkie_dodanie_zalacznikow",
    "udostepnij_pliki",
    "wskaznik_zalacznikow",
]
