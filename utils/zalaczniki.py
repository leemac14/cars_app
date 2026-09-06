"""Załączniki i zdjęcia: wybór, podgląd, wskaźniki."""

import asyncio
import db
import flet as ft
import os

from .dialogi import otworz_dialog, pokaz_komunikat, zamknij_dialog


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
        "Dodaj / zmień załącznik (zdjęcie, PDF)" if tylko_zdjecie
        else "Dodaj / zmień załącznik (możesz zaznaczyć kilka zdjęć naraz)"
    )
    btn_wybierz = ft.TextButton(etykieta_przycisku, icon=ft.Icons.ATTACH_FILE, on_click=wybierz)

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

    btn_dodaj = ft.TextButton("Wybierz zdjęcia (można zaznaczyć od razu kilka)", icon=ft.Icons.PHOTO_CAMERA, on_click=wybierz)
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


__all__ = [
    "abs_zalacznik",
    "komponent_wielu_nowych_zdjec",
    "komponent_zalacznika",
    "pokaz_podglad_zalacznika",
    "szybkie_dodanie_zdjecia",
    "wskaznik_zalacznika",
]
