import flet as ft
import os
import shutil
import inspect
import zipfile
import tempfile
import io
import asyncio
import db
import sync
import utils
from state import AppState

from views.main_view import MainView
from views.history_view import HistoriaView, WizytyZbiorczeView
from views.forms_view import (
    FormularzAutoView, FormularzTankowanieView, FormularzInneView,
    FormularzWizytyView, FormularzInterwalView, FormularzZadanieView,
    FormularzWpisView
)
from views.settings_view import UstawieniaView
from views.todo_view import DoZrobieniaView, FormularzDoZrobieniaView
from views.garage_view import MagazynView, FormularzOponyView, FormularzCzesciView
from views.body_view import KaroseriaView, FormularzZdjecieKaroseriiView
from views.porownanie_view import PorownanieView
from views.przebieg_view import OdczytyPrzebieguView
from views.eksport_view import EksportView
from views.import_view import ImportCSVView
from views.kalkulator_view import KalkulatorTrasyView
from views.wspoldzielenie_view import WspoldzielenieView
from views.timeline_view import TimelineView
from views.search_view import SzukajView
from views.podzial_view import PodzialKosztowView

def main(page: ft.Page):
    page.title = "Flota Mobile"
    page.window.width = 400
    page.window.height = 800
    page.padding = 0
    page.spacing = 0

    db.init_db()

    kolor_ustawiony = db.pobierz_kolor_motywu()

    MAPA_TRYBU_MOTYWU = {"jasny": ft.ThemeMode.LIGHT, "ciemny": ft.ThemeMode.DARK, "system": ft.ThemeMode.SYSTEM}

    def zastosuj_tryb_motywu():
        page.theme_mode = MAPA_TRYBU_MOTYWU.get(db.pobierz_tryb_motywu(), ft.ThemeMode.LIGHT)

    # Motywy budujemy przez utils.zastosuj_motywy — tam mieszka też wariant
    # „czysta czerń (OLED)”, więc nie trzeba go powtarzać w każdym z miejsc,
    # w których przebudowujemy motyw.
    utils.zastosuj_motywy(page, kolor_ustawiony)
    zastosuj_tryb_motywu()

    # Zapamiętujemy ostatnio zastosowany kolor motywu i auto, dla którego go
    # policzyliśmy — każdy pojazd może mieć teraz własny kolor interfejsu.
    kolor_motywu_zastosowany = {"nazwa": kolor_ustawiony, "auto_id": None}

    app_state = AppState()

    # ---- EKSPORT / IMPORT (Z poziomu głównego modułu) ----
    def _skopiuj_baze(sciezka_zrodlowa, sciezka_docelowa):
        import sqlite3
        zrodlo = sqlite3.connect(sciezka_zrodlowa)
        cel = sqlite3.connect(sciezka_docelowa)
        try:
            zrodlo.backup(cel)
        finally:
            cel.close()
            zrodlo.close()

    def _przygotuj_zip_eksportu():
        """Buduje archiwum ZIP w pamięci: spójna kopia bazy (przez SQLite backup) + folder załączników."""
        bufor = io.BytesIO()
        nazwa_folderu_zal = os.path.basename(db.FOLDER_ZALACZNIKI)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_baza = os.path.join(tmp, os.path.basename(db.BAZA_DANYCH))
            if os.path.exists(db.BAZA_DANYCH):
                _skopiuj_baze(db.BAZA_DANYCH, tmp_baza)
            with zipfile.ZipFile(bufor, "w", zipfile.ZIP_DEFLATED) as zf:
                if os.path.exists(tmp_baza):
                    zf.write(tmp_baza, arcname=os.path.basename(db.BAZA_DANYCH))
                if os.path.isdir(db.FOLDER_ZALACZNIKI):
                    for korzen, _, pliki in os.walk(db.FOLDER_ZALACZNIKI):
                        for nazwa_pliku in pliki:
                            pelna_sciezka = os.path.join(korzen, nazwa_pliku)
                            arcname = os.path.join(nazwa_folderu_zal, os.path.relpath(pelna_sciezka, db.FOLDER_ZALACZNIKI))
                            zf.write(pelna_sciezka, arcname=arcname)
        bufor.seek(0)
        return bufor.read()

    def _zapisz_tymczasowy_zip():
        sciezka = os.path.join(tempfile.gettempdir(), "kopia_baza.zip")
        with open(sciezka, "wb") as f:
            f.write(_przygotuj_zip_eksportu())
        return sciezka

    def _wczytaj_zip_importu(sciezka_zip):
        """Rozpakowuje archiwum kopii zapasowej: bazę danych oraz folder załączników."""
        with zipfile.ZipFile(sciezka_zip, "r") as zf:
            nazwa_bazy = os.path.basename(db.BAZA_DANYCH)
            if nazwa_bazy not in zf.namelist():
                raise ValueError("Archiwum nie zawiera pliku bazy danych.")

            with tempfile.TemporaryDirectory() as tmp:
                tmp_abs = os.path.abspath(tmp)
                for member in zf.namelist():
                    docelowa = os.path.abspath(os.path.join(tmp_abs, member))
                    if not docelowa.startswith(tmp_abs + os.sep):
                        raise ValueError("Archiwum zawiera nieprawidłową ścieżkę pliku.")

                zf.extractall(tmp)
                shutil.copyfile(os.path.join(tmp, nazwa_bazy), db.BAZA_DANYCH)

                if os.path.isdir(db.FOLDER_ZALACZNIKI):
                    shutil.rmtree(db.FOLDER_ZALACZNIKI, ignore_errors=True)

                nazwa_folderu_zal = os.path.basename(db.FOLDER_ZALACZNIKI)
                folder_tmp = os.path.join(tmp, nazwa_folderu_zal)
                if os.path.isdir(folder_tmp):
                    shutil.copytree(folder_tmp, db.FOLDER_ZALACZNIKI)

        os.makedirs(db.FOLDER_ZALACZNIKI, exist_ok=True)

    def wykonaj_import(sciezka_zrodlowa):
        import sqlite3
        baza_bak = db.BAZA_DANYCH + ".bak"
        folder_bak = db.FOLDER_ZALACZNIKI + "_bak"
        kopia_zrobiona = False

        def przywroc_kopie_bezpieczenstwa():
            """Cofa bazę i załączniki do stanu sprzed nieudanego importu."""
            try:
                if os.path.exists(baza_bak):
                    shutil.copyfile(baza_bak, db.BAZA_DANYCH)
                if os.path.isdir(folder_bak):
                    if os.path.isdir(db.FOLDER_ZALACZNIKI):
                        shutil.rmtree(db.FOLDER_ZALACZNIKI, ignore_errors=True)
                    shutil.copytree(folder_bak, db.FOLDER_ZALACZNIKI)
                db.init_db()
                app_state.auto_id = None
                db.zainicjuj_domyslne_auto(app_state)
            except Exception:
                pass

        try:
            if not sciezka_zrodlowa or not os.path.exists(sciezka_zrodlowa):
                utils.pokaz_komunikat(page, "Nie można odczytać wybranego pliku.", ft.Colors.RED_700)
                return

            if os.path.exists(db.BAZA_DANYCH):
                shutil.copyfile(db.BAZA_DANYCH, baza_bak)
            if os.path.isdir(db.FOLDER_ZALACZNIKI):
                shutil.rmtree(folder_bak, ignore_errors=True)
                shutil.copytree(db.FOLDER_ZALACZNIKI, folder_bak)
            kopia_zrobiona = True

            if sciezka_zrodlowa.lower().endswith(".zip"):
                _wczytaj_zip_importu(sciezka_zrodlowa)
            else:
                # Stary format kopii zapasowej (sam plik .db, bez załączników)
                _skopiuj_baze(sciezka_zrodlowa, db.BAZA_DANYCH)

            db.init_db()

            app_state.auto_id = None
            app_state.wybrane_zadanie_id = None
            app_state.wybrane_zadanie_nazwa = ""
            db.zainicjuj_domyslne_auto(app_state)
            
            kolor_biezacy = db.pobierz_kolor_auta(app_state.auto_id)
            # Import podmienił całą bazę, więc razem z kolorem mógł się zmienić
            # także przełącznik czystej czerni — czyścimy jego pamięć podręczną.
            utils.odswiez_cache_czerni()
            utils.zastosuj_motywy(page, kolor_biezacy)
            zastosuj_tryb_motywu()
            page.update()
            kolor_motywu_zastosowany["nazwa"] = kolor_biezacy
            kolor_motywu_zastosowany["auto_id"] = app_state.auto_id
            
            utils.przejdz(page, "/")
            utils.pokaz_komunikat(page, "Pomyślnie wczytano bazę! Stara zapisana jako .bak")
        except sqlite3.DatabaseError:
            if kopia_zrobiona:
                przywroc_kopie_bezpieczenstwa()
                utils.przejdz(page, "/")
            utils.pokaz_komunikat(page, "Wybrany plik nie jest poprawną bazą danych SQLite. Przywrócono poprzednią bazę.", ft.Colors.RED_700)
        except Exception as ex:
            if kopia_zrobiona:
                przywroc_kopie_bezpieczenstwa()
                utils.przejdz(page, "/")
            utils.pokaz_komunikat(page, f"Błąd importu: {ex}. Przywrócono poprzednią bazę.", ft.Colors.RED_700)

    file_picker = ft.FilePicker()
    _pending_export = {"bajty": None}  # bufor na dane, gdy plik zapisu pochodzi z eksportu innego niż kopia bazy

    def on_file_result(e):
        async def _obsluz():
            if getattr(e, "files", None) and len(e.files) > 0:
                await asyncio.to_thread(wykonaj_import, e.files[0].path)
            elif getattr(e, "path", None):
                try:
                    if _pending_export["bajty"] is not None:
                        dane_zapisu = _pending_export["bajty"]
                        _pending_export["bajty"] = None
                    else:
                        dane_zapisu = await asyncio.to_thread(_przygotuj_zip_eksportu)
                    with open(e.path, "wb") as f:
                        f.write(dane_zapisu)
                    utils.pokaz_komunikat(page, "Zapisano pomyślnie!", ft.Colors.GREEN_700)
                except Exception as ex:
                    utils.pokaz_komunikat(page, f"Błąd zapisu: {ex}", ft.Colors.RED_700)
        page.run_task(_obsluz)

    if hasattr(file_picker, "on_result"):
        file_picker.on_result = on_file_result

    if hasattr(page, "services"):
        page.services.append(file_picker)
    else:
        page.overlay.append(file_picker)

    zalacznik_picker = ft.FilePicker()
    if hasattr(page, "services"):
        page.services.append(zalacznik_picker)
    else:
        page.overlay.append(zalacznik_picker)
    page.zalacznik_picker = zalacznik_picker

    share_service = None
    if hasattr(ft, "Share"):
        share_service = ft.Share()
        if hasattr(page, "services"):
            page.services.append(share_service)
        else:
            page.overlay.append(share_service)
    page.share_service = share_service  # <-- NOWE: udostępniamy serwis widokom (np. podgląd PDF)

    async def eksportuj_baze(e=None):
        dlg_ladowania = utils.pokaz_ladowanie(page, "Przygotowywanie kopii zapasowej...")

        def _schowaj_ladowanie():
            nonlocal dlg_ladowania
            if dlg_ladowania is not None:
                utils.ukryj_ladowanie(page, dlg_ladowania)
                dlg_ladowania = None

        try:
            if page.platform in ["android", "ios"] and share_service is not None:
                try:
                    sciezka_zip = await asyncio.to_thread(_zapisz_tymczasowy_zip)
                    _schowaj_ladowanie()
                    if hasattr(share_service, "share_files_async"):
                        await share_service.share_files_async([sciezka_zip])
                    else:
                        res = share_service.share_files([sciezka_zip])
                        if inspect.iscoroutine(res):
                            await res
                    return
                except Exception:
                    pass

            zip_bytes = await asyncio.to_thread(_przygotuj_zip_eksportu)
            _schowaj_ladowanie()

            if hasattr(page, "services") and not hasattr(file_picker, "on_result"):
                if hasattr(file_picker, "save_file_async"):
                    res = await file_picker.save_file_async(file_name="kopia_baza.zip", src_bytes=zip_bytes)
                else:
                    res = await file_picker.save_file(file_name="kopia_baza.zip", src_bytes=zip_bytes)

                if res:
                    utils.pokaz_komunikat(page, "Zapisano pomyślnie!", ft.Colors.GREEN_700)
            else:
                file_picker.save_file(file_name="kopia_baza.zip")
        except Exception as ex:
            utils.pokaz_komunikat(page, f"Błąd otwierania menedżera: {ex}", ft.Colors.RED_700)
        finally:
            _schowaj_ladowanie()

    async def _zapisz_bajty_pliku(nazwa_pliku, dane_bytes):
        """Uniwersalny zapis/udostępnienie gotowych bajtów pliku — współdzielony mechanizm
        używany zarówno przy eksporcie kopii bazy, jak i nowym eksporcie danych CSV/PDF."""
        if page.platform in ["android", "ios"] and share_service is not None:
            try:
                sciezka_tmp = os.path.join(tempfile.gettempdir(), nazwa_pliku)
                with open(sciezka_tmp, "wb") as f:
                    f.write(dane_bytes)
                if hasattr(share_service, "share_files_async"):
                    await share_service.share_files_async([sciezka_tmp])
                else:
                    res = share_service.share_files([sciezka_tmp])
                    if inspect.iscoroutine(res):
                        await res
                return
            except Exception:
                pass

        try:
            if hasattr(page, "services") and not hasattr(file_picker, "on_result"):
                if hasattr(file_picker, "save_file_async"):
                    res = await file_picker.save_file_async(file_name=nazwa_pliku, src_bytes=dane_bytes)
                else:
                    res = await file_picker.save_file(file_name=nazwa_pliku, src_bytes=dane_bytes)
                if res:
                    utils.pokaz_komunikat(page, "Wyeksportowano pomyślnie!", ft.Colors.GREEN_700)
            else:
                _pending_export["bajty"] = dane_bytes
                file_picker.save_file(file_name=nazwa_pliku)
        except Exception as ex:
            utils.pokaz_komunikat(page, f"Błąd otwierania menedżera: {ex}", ft.Colors.RED_700)

    def _bezpieczna_nazwa_pliku(tekst):
        oczyszczone = "".join(c if c.isalnum() else "_" for c in str(tekst))
        return oczyszczone.strip("_") or "pojazd"

    async def eksportuj_dane_zaawansowane(auto_id, auto_nazwa, kategorie, od_d, do_d, opis_okresu, format_pliku, dolacz_podsumowanie, dolacz_paszport=False, po_zakonczeniu=None):
        try:
            dane = await asyncio.to_thread(db.pobierz_dane_eksportu, auto_id, kategorie, od_d, do_d)
            nazwa_bazowa = _bezpieczna_nazwa_pliku(auto_nazwa)

            if format_pliku == "pdf":
                podsumowanie = None
                if dolacz_podsumowanie:
                    podsumowanie = await asyncio.to_thread(db.oblicz_podsumowanie_okresu, auto_id, od_d, do_d)

                dane_paszportu = {}
                if dolacz_paszport:
                    dane_paszportu = await asyncio.to_thread(db.pobierz_dane_paszportu, auto_id)

                try:
                    dane_pliku = await asyncio.to_thread(
                        db.generuj_pdf_raportu, auto_nazwa, dane, opis_okresu, podsumowanie,
                        dolacz_paszport, **dane_paszportu
                    )
                except RuntimeError as ex:
                    utils.pokaz_komunikat(page, str(ex), ft.Colors.RED_700)
                    return
                nazwa_pliku = f"paszport_{nazwa_bazowa}.pdf" if dolacz_paszport else f"raport_{nazwa_bazowa}.pdf"
            else:
                dane_pliku, rozszerzenie = await asyncio.to_thread(db.generuj_eksport_csv, dane)
                nazwa_pliku = f"eksport_{nazwa_bazowa}.{rozszerzenie}"

            await _zapisz_bajty_pliku(nazwa_pliku, dane_pliku)
        except Exception as ex:
            utils.pokaz_komunikat(page, f"Błąd eksportu: {ex}", ft.Colors.RED_700)
        finally:
            if po_zakonczeniu:
                po_zakonczeniu()

    async def importuj_baze(e=None):
        try:
            if hasattr(page, "services") and not hasattr(file_picker, "on_result"):
                if hasattr(file_picker, "pick_files_async"):
                    files = await file_picker.pick_files_async(file_type=ft.FilePickerFileType.ANY)
                else:
                    files = await file_picker.pick_files(file_type=ft.FilePickerFileType.ANY)

                if files and len(files) > 0:
                    await asyncio.to_thread(wykonaj_import, files[0].path)  
            else:
                file_picker.pick_files()
        except Exception as ex:
            utils.pokaz_komunikat(page, f"Błąd otwierania menedżera: {ex}", ft.Colors.RED_700)

    def przelacz_tryb(e=None):
        obecny = db.pobierz_tryb_motywu()
        nowy = db.KOLEJNOSC_TRYBOW_MOTYWU[(db.KOLEJNOSC_TRYBOW_MOTYWU.index(obecny) + 1) % 3]
        db.zapisz_tryb_motywu(nowy)
        utils.zastosuj_motywy(page, db.pobierz_kolor_auta(app_state.auto_id))
        zastosuj_tryb_motywu()
        utils.przejdz(page, page.route)

    # ---- SYSTEM ROUTINGU ----
    def trasa_zmieniona(e):
        db.zainicjuj_domyslne_auto(app_state)

        # Motyw przebudowujemy TYLKO gdy kolor faktycznie się zmienił (zapis
        # ustawień, zmiana koloru pojazdu, przełączenie aktywnego auta, import
        # bazy) — nie przy każdej nawigacji. Każdy pojazd może mieć własny
        # kolor (db.pobierz_kolor_auta), z fallbackiem na globalny domyślny.
        kolor_biezacy = db.pobierz_kolor_auta(app_state.auto_id)
        if kolor_biezacy != kolor_motywu_zastosowany["nazwa"] or app_state.auto_id != kolor_motywu_zastosowany["auto_id"]:
            utils.zastosuj_motywy(page, kolor_biezacy)
            kolor_motywu_zastosowany["nazwa"] = kolor_biezacy
            kolor_motywu_zastosowany["auto_id"] = app_state.auto_id

        trasa = page.route
        segmenty = [s for s in trasa.split("/") if s != ""]

        page.views.clear()
        page.views.append(MainView(page, app_state, eksportuj_baze, importuj_baze, przelacz_tryb))

        if not segmenty:
            pass
        elif segmenty[0] == "auto" and len(segmenty) >= 2 and segmenty[1] == "nowy":
            page.views.append(FormularzAutoView(page, app_state, None))
        elif segmenty[0] == "auto" and len(segmenty) >= 3 and segmenty[1] == "edytuj":
            page.views.append(FormularzAutoView(page, app_state, utils.parsuj_int(segmenty[2], None)))
        elif segmenty[0] == "historia" and len(segmenty) >= 2:
            page.views.append(HistoriaView(page, app_state, utils.parsuj_int(segmenty[1], None)))
        elif segmenty[0] == "wizyty":
            page.views.append(WizytyZbiorczeView(page, app_state))
            if len(segmenty) >= 2 and segmenty[1] == "nowa":
                page.views.append(FormularzWizytyView(page, app_state, None))
            elif len(segmenty) >= 3 and segmenty[1] == "edytuj":
                page.views.append(FormularzWizytyView(page, app_state, utils.parsuj_int(segmenty[2], None)))
        elif segmenty[0] == "tankowanie" and len(segmenty) >= 2 and segmenty[1] == "nowe":
            page.views.append(FormularzTankowanieView(page, app_state, None))
        elif segmenty[0] == "tankowanie" and len(segmenty) >= 3 and segmenty[1] == "edytuj":
            page.views.append(FormularzTankowanieView(page, app_state, utils.parsuj_int(segmenty[2], None)))
        elif segmenty[0] == "inne" and len(segmenty) >= 2 and segmenty[1] == "nowy":
            page.views.append(FormularzInneView(page, app_state, None))
        elif segmenty[0] == "inne" and len(segmenty) >= 3 and segmenty[1] == "edytuj":
            page.views.append(FormularzInneView(page, app_state, utils.parsuj_int(segmenty[2], None)))
        elif segmenty[0] == "wpis":
            if len(segmenty) >= 3 and segmenty[1] == "nowy":
                z_id = utils.parsuj_int(segmenty[2], None)
                if z_id:
                    page.views.append(HistoriaView(page, app_state, z_id))
                page.views.append(FormularzWpisView(page, app_state, None, z_id))
            elif len(segmenty) >= 3 and segmenty[1] == "edytuj":
                h_id = utils.parsuj_int(segmenty[2], None)
                z_id_nadrzedny = None
                if h_id:
                    with db.polacz_baze() as conn:
                        c = conn.cursor()
                        c.execute("SELECT zadanie_id FROM historia WHERE id=?", (h_id,))
                        w = c.fetchone()
                        z_id_nadrzedny = w[0] if w else None
                if z_id_nadrzedny:
                    page.views.append(HistoriaView(page, app_state, z_id_nadrzedny))
                page.views.append(FormularzWpisView(page, app_state, h_id, None))
        elif segmenty[0] == "interwal" and len(segmenty) >= 2:
            page.views.append(FormularzInterwalView(page, app_state, utils.parsuj_int(segmenty[1], None)))
        elif segmenty[0] == "zadanie" and len(segmenty) >= 2 and segmenty[1] == "nowy":
            page.views.append(FormularzZadanieView(page, app_state, None))
        elif segmenty[0] == "zadanie" and len(segmenty) >= 3 and segmenty[1] == "edytuj":
            page.views.append(FormularzZadanieView(page, app_state, utils.parsuj_int(segmenty[2], None)))
        elif segmenty[0] == "magazyn":
            page.views.append(MagazynView(page, app_state))
            if len(segmenty) >= 3 and segmenty[1] == "opony" and segmenty[2] == "nowy":
                page.views.append(FormularzOponyView(page, app_state, None))
            elif len(segmenty) >= 4 and segmenty[1] == "opony" and segmenty[2] == "edytuj":
                page.views.append(FormularzOponyView(page, app_state, utils.parsuj_int(segmenty[3], None)))
            elif len(segmenty) >= 3 and segmenty[1] == "czesci" and segmenty[2] == "nowa":
                page.views.append(FormularzCzesciView(page, app_state, None))
            elif len(segmenty) >= 4 and segmenty[1] == "czesci" and segmenty[2] == "edytuj":
                page.views.append(FormularzCzesciView(page, app_state, utils.parsuj_int(segmenty[3], None)))
        elif segmenty[0] == "karoseria":
            page.views.append(KaroseriaView(page, app_state))
            if len(segmenty) >= 2 and segmenty[1] == "nowe":
                page.views.append(FormularzZdjecieKaroseriiView(page, app_state, None))
            elif len(segmenty) >= 3 and segmenty[1] == "edytuj":
                page.views.append(FormularzZdjecieKaroseriiView(page, app_state, utils.parsuj_int(segmenty[2], None)))
        elif segmenty[0] == "ustawienia":
            page.views.append(UstawieniaView(page, app_state))
        elif segmenty[0] == "porownanie":
            page.views.append(PorownanieView(page, app_state))
        elif segmenty[0] == "wspoldzielenie":
            page.views.append(WspoldzielenieView(page, app_state))
        elif segmenty[0] == "podzial":
            page.views.append(PodzialKosztowView(page, app_state))
        elif segmenty[0] == "przebieg":
            page.views.append(OdczytyPrzebieguView(page, app_state))
        elif segmenty[0] == "eksport":
            page.views.append(EksportView(page, app_state, eksportuj_dane_zaawansowane))
        elif segmenty[0] == "import":
            page.views.append(ImportCSVView(page, app_state))
        elif segmenty[0] == "kalkulator":
            page.views.append(KalkulatorTrasyView(page, app_state))
        elif segmenty[0] == "timeline":
            page.views.append(TimelineView(page, app_state))
        elif segmenty[0] == "szukaj":
            page.views.append(SzukajView(page, app_state))
        elif segmenty[0] == "do-zrobienia":
            page.views.append(DoZrobieniaView(page, app_state))
            if len(segmenty) >= 2 and segmenty[1] == "nowe":
                page.views.append(FormularzDoZrobieniaView(page, app_state, None))
            elif len(segmenty) >= 3 and segmenty[1] == "edytuj":
                page.views.append(FormularzDoZrobieniaView(page, app_state, utils.parsuj_int(segmenty[2], None)))

        page.update()

    def widok_zamkniety(e):
        if len(page.views) > 1:
            page.views.pop()
            utils.przejdz(page, page.views[-1].route)

    def na_zmiane_rozmiaru(e):
        if page.views:
            aktywny_widok = page.views[-1]
            if hasattr(aktywny_widok, "dostosuj_wysokosc_listy"):
                aktywny_widok.dostosuj_wysokosc_listy()

    page.on_resized = na_zmiane_rozmiaru

    page.on_route_change = trasa_zmieniona
    page.on_view_pop = widok_zamkniety

    async def _nadgon_kolejke_sync():
        try:
            await asyncio.to_thread(sync.przetworz_kolejke_sync, 10)
        except Exception:
            pass  # start aplikacji nigdy nie może się wywalić przez brak sieci
    page.run_task(_nadgon_kolejke_sync)

    utils.przejdz(page, page.route or "/")

ft.run(main)