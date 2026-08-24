import flet as ft
from datetime import datetime, timedelta
import sqlite3
import os
import re
import shutil
from contextlib import contextmanager

# ==========================================
# KONFIGURACJA I BAZA DANYCH
# ==========================================
BAZA_DANYCH = 'flota_zadania.db'
KATEGORIE_INNE = ["Ubezpieczenie", "Myjnia i Kosmetyki", "Parking i Autostrady", "Raty i Leasing", "Akcesoria / Wyposażenie", "Inne"]
DOMYSLNE_ZADANIA = [
    "🛢️ Olej silnikowy i filtr", "💨 Filtr powietrza", "🌬️ Filtr kabinowy",
    "⚙️ Pasek / Łańcuch rozrządu", "🛞 Wymiana opon / Kół", "🛑 Klocki hamulcowe", "💿 Tarcze hamulcowe"
]
ROK_MIN = 1950

@contextmanager
def polacz_baze():
    conn = sqlite3.connect(BAZA_DANYCH)
    conn.execute('PRAGMA foreign_keys = ON;')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with polacz_baze() as conn:
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS samochody (id INTEGER PRIMARY KEY AUTOINCREMENT, nazwa TEXT UNIQUE NOT NULL)")

        cursor.execute("PRAGMA table_info(samochody)")
        kolumny = [k[1] for k in cursor.fetchall()]
        if "oc_data" not in kolumny: cursor.execute("ALTER TABLE samochody ADD COLUMN oc_data TEXT")
        if "przeglad_data" not in kolumny: cursor.execute("ALTER TABLE samochody ADD COLUMN przeglad_data TEXT")
        if "nr_rej" not in kolumny: cursor.execute("ALTER TABLE samochody ADD COLUMN nr_rej TEXT")
        if "vin" not in kolumny: cursor.execute("ALTER TABLE samochody ADD COLUMN vin TEXT")
        if "rok_produkcji" not in kolumny: cursor.execute("ALTER TABLE samochody ADD COLUMN rok_produkcji TEXT")

        cursor.execute("CREATE TABLE IF NOT EXISTS zadania (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, nazwa TEXT NOT NULL, data TEXT, przebieg INTEGER, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE)")

        cursor.execute("PRAGMA table_info(zadania)")
        kolumny = [k[1] for k in cursor.fetchall()]
        if "interwal_km" not in kolumny: cursor.execute("ALTER TABLE zadania ADD COLUMN interwal_km INTEGER")
        if "interwal_miesiace" not in kolumny: cursor.execute("ALTER TABLE zadania ADD COLUMN interwal_miesiace INTEGER")

        cursor.execute("CREATE TABLE IF NOT EXISTS wizyty (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, data TEXT NOT NULL, przebieg INTEGER NOT NULL, wykonawca TEXT, koszt_calkowity REAL NOT NULL DEFAULT 0.0, notatki TEXT, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE)")
        cursor.execute("CREATE TABLE IF NOT EXISTS historia (id INTEGER PRIMARY KEY AUTOINCREMENT, wizyta_id INTEGER, zadanie_id INTEGER NOT NULL, data TEXT, przebieg INTEGER, kategoria TEXT, cena REAL DEFAULT 0.0, wykonawca TEXT, FOREIGN KEY (wizyta_id) REFERENCES wizyty(id) ON DELETE CASCADE, FOREIGN KEY (zadanie_id) REFERENCES zadania(id) ON DELETE CASCADE)")

        cursor.execute("PRAGMA table_info(historia)")
        kolumny = [k[1] for k in cursor.fetchall()]
        if "wizyta_id" not in kolumny: cursor.execute("ALTER TABLE historia ADD COLUMN wizyta_id INTEGER")

        cursor.execute("CREATE TABLE IF NOT EXISTS tankowania (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, data TEXT NOT NULL, przebieg INTEGER NOT NULL, dystans REAL NOT NULL DEFAULT 0.0, litry REAL NOT NULL, kwota REAL NOT NULL, do_pelna INTEGER DEFAULT 1, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE)")
        cursor.execute("CREATE TABLE IF NOT EXISTS inne_koszty (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, data TEXT NOT NULL, kategoria TEXT NOT NULL, nazwa TEXT, kwota REAL NOT NULL, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE)")

        # Tabela ustawień aplikacji (np. tryb ciemny) - proste przechowywanie klucz/wartość
        cursor.execute("CREATE TABLE IF NOT EXISTS ustawienia (klucz TEXT PRIMARY KEY, wartosc TEXT)")


# ==========================================
# GŁÓWNA APLIKACJA MOBILNA
# ==========================================
def main(page: ft.Page):
    page.title = "Flota Mobile"
    page.window.width = 400
    page.window.height = 800
    page.padding = 0
    page.spacing = 0

    init_db()

    def przejdz(trasa):
        page.route = trasa
        trasa_zmieniona(None)

    # ---- Motyw i tryb ciemny ----
    page.theme = ft.Theme(color_scheme_seed=ft.Colors.BLUE)
    page.dark_theme = ft.Theme(color_scheme_seed=ft.Colors.BLUE)

    def pobierz_ustawienie(klucz, domyslna=None):
        with polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT wartosc FROM ustawienia WHERE klucz=?", (klucz,))
            w = c.fetchone()
            return w[0] if w else domyslna

    def zapisz_ustawienie(klucz, wartosc):
        with polacz_baze() as conn:
            conn.execute(
                "INSERT INTO ustawienia (klucz, wartosc) VALUES (?, ?) "
                "ON CONFLICT(klucz) DO UPDATE SET wartosc=excluded.wartosc",
                (klucz, wartosc)
            )

    page.theme_mode = ft.ThemeMode.DARK if pobierz_ustawienie("tryb_ciemny", "0") == "1" else ft.ThemeMode.LIGHT

    stan = {
        "auto_id": None,
        "auto_nazwa": "Brak pojazdów",
        "zakladka": 0,
        "stat_podzakladka": 0,  # 0: Liczby, 1: Wykresy, 2: Tabele
        "wybrane_zadanie_id": None,
        "wybrane_zadanie_nazwa": "",
        "sort_zadania": ("nazwa", False),
        "sort_tankowania": ("data", True),
        "sort_inne": ("data", True),
        "sort_historia": ("data", True),
        "sort_wizyty": ("data", True),
    }

    # ==========================================
    # NARZĘDZIA OGÓLNE
    # ==========================================
    def parsuj_date(data_str):
        if not data_str:
            return datetime.min.date()
        for fmt in ('%d.%m.%Y', '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%Y.%m.%d'):
            try:
                return datetime.strptime(str(data_str).strip(), fmt).date()
            except ValueError:
                pass
        return datetime.min.date()

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

    # ---- Bezpieczniejsze parsowanie liczb ----
    def parsuj_int(wartosc, domyslna=0):
        if wartosc is None:
            return domyslna
        tekst = str(wartosc).strip().replace("\xa0", "").replace(" ", "")
        if not tekst:
            return domyslna
        tekst = tekst.replace(",", ".")
        try:
            return int(round(float(tekst)))
        except (ValueError, TypeError):
            dopasowanie = re.search(r"-?\d+", tekst)
            if dopasowanie:
                try:
                    return int(dopasowanie.group())
                except ValueError:
                    pass
            return domyslna

    def parsuj_float(wartosc, domyslna=0.0):
        if wartosc is None:
            return domyslna
        tekst = str(wartosc).strip().replace("\xa0", "").replace(" ", "")
        if not tekst:
            return domyslna
        tekst = tekst.replace(",", ".")
        try:
            return float(tekst)
        except (ValueError, TypeError):
            dopasowanie = re.search(r"-?\d+(\.\d+)?", tekst)
            if dopasowanie:
                try:
                    return float(dopasowanie.group())
                except ValueError:
                    pass
            return domyslna

    FILTR_CALKOWITY = ft.InputFilter(allow=True, regex_string=r"[0-9]", replacement_string="")
    FILTR_DZIESIETNY = ft.InputFilter(allow=True, regex_string=r"[0-9,\.]", replacement_string="")

    def pokaz_komunikat(wiadomosc, kolor=ft.Colors.GREEN_700):
        snack = ft.SnackBar(ft.Text(str(wiadomosc)), bgcolor=kolor)
        if hasattr(page, "open"):
            page.open(snack)
        else:
            page.overlay.append(snack)
            snack.open = True
            page.update()

    def otworz_dno(bottom_sheet):
        if hasattr(page, "open"):
            page.open(bottom_sheet)
        else:
            page.overlay.append(bottom_sheet)
            bottom_sheet.open = True
            page.update()

    def zamknij_dno(bottom_sheet):
        if hasattr(page, "close"):
            page.close(bottom_sheet)
        else:
            bottom_sheet.open = False
            if bottom_sheet in page.overlay:
                page.overlay.remove(bottom_sheet)
            page.update()

    # ---- Dialogi ----
    def otworz_dialog(kontrolka):
        if hasattr(page, "open"):
            page.open(kontrolka)
        elif hasattr(page, "show_dialog"):
            page.show_dialog(kontrolka)
        else:
            page.overlay.append(kontrolka)
            kontrolka.open = True
            page.update()

    def zamknij_dialog(kontrolka):
        if hasattr(page, "close"):
            page.close(kontrolka)
        elif hasattr(page, "pop_dialog"):
            page.pop_dialog()
        else:
            kontrolka.open = False
            if kontrolka in page.overlay:
                page.overlay.remove(kontrolka)
            page.update()

    # ---- Potwierdzenia usuwania ----
    def potwierdz(tytul, tresc, po_potwierdzeniu, tekst_potwierdzenia="Usuń"):
        def anuluj(e):
            zamknij_dialog(dlg)

        def zatwierdz(e):
            zamknij_dialog(dlg)
            po_potwierdzeniu()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(tytul, weight="bold"),
            content=ft.Text(tresc),
            actions=[
                ft.TextButton("Anuluj", on_click=anuluj),
                ft.TextButton(tekst_potwierdzenia, style=ft.ButtonStyle(color=ft.Colors.RED_700), on_click=zatwierdz),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        otworz_dialog(dlg)

    # ---- Widżet wyboru daty ----
    def pole_daty(label, wartosc_poczatkowa=None):
        pole = ft.TextField(
            label=label,
            value=str(wartosc_poczatkowa) if wartosc_poczatkowa else "",
            read_only=True,
            hint_text="Dotknij ikony, aby wybrać datę",
        )

        def otworz(e):
            try:
                data_pocz = datetime.strptime(pole.value, "%d.%m.%Y") if pole.value else datetime.now()
            except Exception:
                data_pocz = datetime.now()

            def po_wyborze(e2):
                if e2.control.value:
                    pole.value = e2.control.value.strftime("%d.%m.%Y")
                    pole.error_text = None
                    page.update()

            picker = ft.DatePicker(
                value=data_pocz,
                first_date=datetime(1990, 1, 1),
                last_date=datetime(2100, 12, 31),
                on_change=po_wyborze,
                cancel_text="Anuluj",
                confirm_text="Wybierz",
                help_text=label,
            )
            otworz_dialog(picker)

        pole.suffix = ft.IconButton(icon=ft.Icons.CALENDAR_MONTH, tooltip="Wybierz datę", on_click=otworz, icon_size=20)
        return pole

    def pokaz_bledy_formularza(bledy):
        for kontrolka, komunikat in bledy:
            kontrolka.error_text = komunikat
        page.update()
        pokaz_komunikat("Popraw zaznaczone pola formularza.", ft.Colors.RED_700)

    def posortuj_liste(lista, klucz_stanu, opcje):
        pole_akt, malejaco = stan.get(klucz_stanu, (opcje[0][1], False))
        for _, pole, fn in opcje:
            if pole == pole_akt:
                lista.sort(key=fn, reverse=malejaco)
                break
        return lista

    def przycisk_sortowania(klucz_stanu, opcje):
        pole_akt, malejaco_akt = stan.get(klucz_stanu, (opcje[0][1], False))

        def zmien_pole(e):
            _, mal = stan.get(klucz_stanu, (opcje[0][1], False))
            stan[klucz_stanu] = (e.control.value, mal)
            odswiez_biezacy_widok()

        def zmien_kierunek(e):
            pole, mal = stan.get(klucz_stanu, (opcje[0][1], False))
            stan[klucz_stanu] = (pole, not mal)
            odswiez_biezacy_widok()

        dd = ft.Dropdown(
            value=pole_akt,
            options=[ft.DropdownOption(key=pole, text=etykieta) for etykieta, pole, _ in opcje],
            on_select=zmien_pole,
            width=170,
        )
        return ft.Row([
            ft.Text("Sortuj:", size=13, color=ft.Colors.ON_SURFACE_VARIANT),
            dd,
            ft.IconButton(
                icon=ft.Icons.ARROW_DOWNWARD if malejaco_akt else ft.Icons.ARROW_UPWARD,
                tooltip="Malejąco" if malejaco_akt else "Rosnąco",
                icon_size=18,
                on_click=zmien_kierunek
            )
        ], spacing=5)

    def pobierz_aktualny_przebieg():
        if not stan["auto_id"]: return 0
        with polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT MAX(przebieg) FROM tankowania WHERE auto_id = ?", (stan["auto_id"],))
            mt = int(c.fetchone()[0] or 0)
            c.execute("SELECT MAX(przebieg) FROM wizyty WHERE auto_id = ?", (stan["auto_id"],))
            mw = int(c.fetchone()[0] or 0)
            c.execute("SELECT MAX(h.przebieg) FROM historia h JOIN zadania z ON h.zadanie_id = z.id WHERE z.auto_id = ?", (stan["auto_id"],))
            mh = int(c.fetchone()[0] or 0)
            return max(mt, mw, mh)

    def aktualizuj_najnowszy_wpis(zadanie_id):
        with polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT data, przebieg FROM historia WHERE zadanie_id = ?", (zadanie_id,))
            wpisy = c.fetchall()
            if wpisy:
                wpisy.sort(key=lambda x: (parsuj_date(x[0]), int(x[1] or 0)), reverse=True)
                c.execute("UPDATE zadania SET data=?, przebieg=? WHERE id=?", (wpisy[0][0], int(wpisy[0][1] or 0), zadanie_id))
            else:
                c.execute("UPDATE zadania SET data=NULL, przebieg=NULL WHERE id=?", (zadanie_id,))

    def przelicz_wszystkie_zadania():
        if not stan["auto_id"]: return
        with polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT id FROM zadania WHERE auto_id = ?", (stan["auto_id"],))
            for r in c.fetchall():
                aktualizuj_najnowszy_wpis(r[0])

    def usun_auto():
        if not stan["auto_id"]: return
        nazwa = stan["auto_nazwa"]

        def wykonaj():
            with polacz_baze() as c:
                c.execute("DELETE FROM samochody WHERE id=?", (stan["auto_id"],))
            stan["auto_id"] = None
            zainicjuj_domyslne_auto()
            przejdz("/")
            pokaz_komunikat("Usunięto pojazd.")

        potwierdz(
            "Usunąć pojazd?",
            f"Czy na pewno chcesz usunąć „{nazwa}”? Zostanie usunięta cała historia serwisowa, tankowania, wizyty i koszty tego pojazdu. Tej operacji nie można cofnąć.",
            wykonaj,
        )

    def przelacz_tryb_ciemny(e=None):
        nowy = ft.ThemeMode.LIGHT if page.theme_mode == ft.ThemeMode.DARK else ft.ThemeMode.DARK
        page.theme_mode = nowy
        zapisz_ustawienie("tryb_ciemny", "1" if nowy == ft.ThemeMode.DARK else "0")
        odswiez_biezacy_widok()

    # ==========================================
    # TRANSFER BAZY DANYCH (EKSPORT / IMPORT)
    # ==========================================
    def _skopiuj_baze(sciezka_zrodlowa, sciezka_docelowa):
        zrodlo = sqlite3.connect(sciezka_zrodlowa)
        cel = sqlite3.connect(sciezka_docelowa)
        try:
            zrodlo.backup(cel)
        finally:
            cel.close()
            zrodlo.close()

    def wykonaj_import(sciezka_zrodlowa):
        try:
            if not sciezka_zrodlowa or not os.path.exists(sciezka_zrodlowa):
                pokaz_komunikat("Nie można odczytać wybranego pliku.", ft.Colors.RED_700)
                return

            if os.path.exists(BAZA_DANYCH):
                shutil.copyfile(BAZA_DANYCH, BAZA_DANYCH + ".bak")
            _skopiuj_baze(sciezka_zrodlowa, BAZA_DANYCH)
            init_db()

            stan["auto_id"] = None
            stan["wybrane_zadanie_id"] = None
            stan["wybrane_zadanie_nazwa"] = ""
            zainicjuj_domyslne_auto()
            przejdz("/")
            pokaz_komunikat("Pomyślnie wczytano bazę! Stara zapisana jako .bak")
        except sqlite3.DatabaseError:
            pokaz_komunikat("Wybrany plik nie jest poprawną bazą danych SQLite.", ft.Colors.RED_700)
        except Exception as ex:
            pokaz_komunikat(f"Błąd importu: {ex}", ft.Colors.RED_700)

    file_picker = ft.FilePicker()

    def on_file_result(e):
        if getattr(e, "files", None) and len(e.files) > 0:
            wykonaj_import(e.files[0].path)
        elif getattr(e, "path", None):
            try:
                _skopiuj_baze(BAZA_DANYCH, e.path)
                pokaz_komunikat("Zapisano pomyślnie!", ft.Colors.GREEN_700)
            except Exception as ex:
                pokaz_komunikat(f"Błąd zapisu: {ex}", ft.Colors.RED_700)

    if hasattr(file_picker, "on_result"):
        file_picker.on_result = on_file_result

    if hasattr(page, "services"):
        page.services.append(file_picker)
    else:
        page.overlay.append(file_picker)

    share_service = None
    if hasattr(ft, "Share"):
        share_service = ft.Share()
        if hasattr(page, "services"):
            page.services.append(share_service)
        else:
            page.overlay.append(share_service)

    async def eksportuj_baze(e=None):
        if page.platform in ["android", "ios"] and share_service is not None:
            try:
                import inspect
                if hasattr(share_service, "share_files_async"):
                    await share_service.share_files_async([BAZA_DANYCH])
                else:
                    res = share_service.share_files([BAZA_DANYCH])
                    if inspect.iscoroutine(res):
                        await res
                return
            except Exception:
                pass

        try:
            db_bytes = None
            if os.path.exists(BAZA_DANYCH):
                with open(BAZA_DANYCH, "rb") as f:
                    db_bytes = f.read()

            if hasattr(page, "services") and not hasattr(file_picker, "on_result"):
                if hasattr(file_picker, "save_file_async"):
                    res = await file_picker.save_file_async(file_name="kopia_flota.db", src_bytes=db_bytes)
                else:
                    res = await file_picker.save_file(file_name="kopia_flota.db", src_bytes=db_bytes)

                if res:
                    pokaz_komunikat("Zapisano pomyślnie!", ft.Colors.GREEN_700)
            else:
                file_picker.save_file(file_name="kopia_flota.db")
        except Exception as ex:
            pokaz_komunikat(f"Błąd otwierania menedżera: {ex}", ft.Colors.RED_700)

    async def importuj_baze(e=None):
        try:
            if hasattr(page, "services") and not hasattr(file_picker, "on_result"):
                if hasattr(file_picker, "pick_files_async"):
                    files = await file_picker.pick_files_async(file_type=ft.FilePickerFileType.ANY)
                else:
                    files = await file_picker.pick_files(file_type=ft.FilePickerFileType.ANY)

                if files and len(files) > 0:
                    wykonaj_import(files[0].path)
            else:
                file_picker.pick_files()
        except Exception as ex:
            pokaz_komunikat(f"Błąd otwierania menedżera: {ex}", ft.Colors.RED_700)

    # ==========================================
    # INFRASTRUKTURA ROUTINGU
    # ==========================================
    def zainicjuj_domyslne_auto():
        with polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT id, nazwa FROM samochody ORDER BY nazwa")
            auta = c.fetchall()
        if not auta:
            stan["auto_id"] = None
            stan["auto_nazwa"] = "Brak pojazdów"
            return
        aktualne_id = stan.get("auto_id")
        for a_id, a_nazwa in auta:
            if a_id == aktualne_id:
                stan["auto_nazwa"] = str(a_nazwa)
                return
        stan["auto_id"] = auta[0][0]
        stan["auto_nazwa"] = str(auta[0][1])

    def zbuduj_menu_aut():
        with polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT id, nazwa FROM samochody ORDER BY nazwa")
            auta = c.fetchall()

        def zmien_auto(aid, an):
            stan["auto_id"] = aid
            stan["auto_nazwa"] = str(an)
            odswiez_biezacy_widok()

        pozycje = []
        for a_id, a_nazwa in auta:
            zaznaczone = a_id == stan["auto_id"]
            pozycje.append(ft.PopupMenuItem(
                content=ft.Row([
                    ft.Icon(ft.Icons.CHECK, size=16, visible=zaznaczone),
                    ft.Text(str(a_nazwa), weight="bold" if zaznaczone else "normal"),
                ]),
                on_click=lambda e, aid=a_id, an=a_nazwa: zmien_auto(aid, an),
            ))

        pozycje.append(ft.PopupMenuItem(content=ft.Divider()))
        pozycje.append(ft.PopupMenuItem(
            content=ft.Row([ft.Icon(ft.Icons.ADD, color=ft.Colors.GREEN), ft.Text("Dodaj pojazd")]),
            on_click=lambda e: przejdz("/auto/nowy"),
        ))
        if auta:
            pozycje.append(ft.PopupMenuItem(
                content=ft.Row([ft.Icon(ft.Icons.EDIT, color=ft.Colors.BLUE), ft.Text("Edytuj pojazd")]),
                on_click=lambda e: przejdz(f"/auto/edytuj/{stan['auto_id']}"),
            ))
            pozycje.append(ft.PopupMenuItem(
                content=ft.Row([ft.Icon(ft.Icons.DELETE, color=ft.Colors.RED), ft.Text("Usuń pojazd")]),
                on_click=lambda e: usun_auto(),
            ))

        pozycje.append(ft.PopupMenuItem(content=ft.Divider()))
        pozycje.append(ft.PopupMenuItem(
            content=ft.Row([ft.Icon(ft.Icons.UPLOAD_FILE, color=ft.Colors.BLUE_700), ft.Text("Eksportuj bazę (kopia)")]),
            on_click=eksportuj_baze,
        ))
        pozycje.append(ft.PopupMenuItem(
            content=ft.Row([ft.Icon(ft.Icons.DOWNLOAD, color=ft.Colors.ORANGE_700), ft.Text("Importuj bazę")]),
            on_click=importuj_baze,
        ))

        pozycje.append(ft.PopupMenuItem(content=ft.Divider()))
        ciemny = page.theme_mode == ft.ThemeMode.DARK
        pozycje.append(ft.PopupMenuItem(
            content=ft.Row([
                ft.Icon(ft.Icons.LIGHT_MODE if ciemny else ft.Icons.DARK_MODE),
                ft.Text("Tryb jasny" if ciemny else "Tryb ciemny"),
            ]),
            on_click=przelacz_tryb_ciemny,
        ))

        return ft.PopupMenuButton(icon=ft.Icons.DIRECTIONS_CAR, tooltip="Zmień pojazd / ustawienia", items=pozycje)

    def pasek_glowny():
        return ft.AppBar(
            title=ft.Text(str(stan["auto_nazwa"]), color=ft.Colors.ON_PRIMARY, weight="bold", size=20),
            center_title=False,
            bgcolor=ft.Colors.PRIMARY,
            actions=[zbuduj_menu_aut()],
        )

    def pasek_z_powrotem(tytul, trasa_powrotu):
        return ft.AppBar(
            title=ft.Text(tytul, color=ft.Colors.ON_PRIMARY, weight="bold", size=18),
            center_title=False,
            bgcolor=ft.Colors.PRIMARY,
            leading=ft.IconButton(icon=ft.Icons.ARROW_BACK, icon_color=ft.Colors.ON_PRIMARY, on_click=lambda e: przejdz(trasa_powrotu)),
        )

    def zbuduj_widok(trasa):
        zainicjuj_domyslne_auto()
        segmenty = [s for s in trasa.split("/") if s != ""]

        if not segmenty:
            appbar, elementy, fab, navbar = zawartosc_main()
        elif segmenty[0] == "auto" and len(segmenty) >= 2 and segmenty[1] == "nowy":
            appbar, elementy, fab, navbar = zawartosc_form_auto(None)
        elif segmenty[0] == "auto" and len(segmenty) >= 3 and segmenty[1] == "edytuj":
            appbar, elementy, fab, navbar = zawartosc_form_auto(parsuj_int(segmenty[2], None) or None)
        elif segmenty[0] == "historia" and len(segmenty) >= 2:
            appbar, elementy, fab, navbar = zawartosc_historia(parsuj_int(segmenty[1], None))
        elif segmenty[0] == "wizyty" and len(segmenty) >= 2 and segmenty[1] == "nowa":
            appbar, elementy, fab, navbar = zawartosc_form_wizyty(None)
        elif segmenty[0] == "wizyty" and len(segmenty) >= 3 and segmenty[1] == "edytuj":
            appbar, elementy, fab, navbar = zawartosc_form_wizyty(parsuj_int(segmenty[2], None) or None)
        elif segmenty[0] == "wizyty":
            appbar, elementy, fab, navbar = zawartosc_wizyty()
        elif segmenty[0] == "tankowanie" and len(segmenty) >= 2 and segmenty[1] == "nowe":
            appbar, elementy, fab, navbar = zawartosc_form_tankowanie(None)
        elif segmenty[0] == "tankowanie" and len(segmenty) >= 3 and segmenty[1] == "edytuj":
            appbar, elementy, fab, navbar = zawartosc_form_tankowanie(parsuj_int(segmenty[2], None) or None)
        elif segmenty[0] == "inne" and len(segmenty) >= 2 and segmenty[1] == "nowy":
            appbar, elementy, fab, navbar = zawartosc_form_inne(None)
        elif segmenty[0] == "inne" and len(segmenty) >= 3 and segmenty[1] == "edytuj":
            appbar, elementy, fab, navbar = zawartosc_form_inne(parsuj_int(segmenty[2], None) or None)
        elif segmenty[0] == "wpis" and len(segmenty) >= 3 and segmenty[1] == "nowy":
            appbar, elementy, fab, navbar = zawartosc_form_wpis(None, parsuj_int(segmenty[2], None))
        elif segmenty[0] == "wpis" and len(segmenty) >= 3 and segmenty[1] == "edytuj":
            appbar, elementy, fab, navbar = zawartosc_form_wpis(parsuj_int(segmenty[2], None), None)
        elif segmenty[0] == "interwal" and len(segmenty) >= 2:
            appbar, elementy, fab, navbar = zawartosc_form_interwal(parsuj_int(segmenty[1], None))
        elif segmenty[0] == "zadanie" and len(segmenty) >= 2 and segmenty[1] == "nowy":
            appbar, elementy, fab, navbar = zawartosc_form_zadanie(None)
        elif segmenty[0] == "zadanie" and len(segmenty) >= 3 and segmenty[1] == "edytuj":
            appbar, elementy, fab, navbar = zawartosc_form_zadanie(parsuj_int(segmenty[2], None) or None)
        else:
            appbar, elementy, fab, navbar = zawartosc_main()

        return ft.View(
            route=trasa,
            appbar=appbar,
            controls=elementy,
            floating_action_button=fab,
            navigation_bar=navbar,
            scroll=ft.ScrollMode.AUTO,
            spacing=15,
            padding=15,
        )

    def odswiez_biezacy_widok():
        if page.views:
            page.views[-1] = zbuduj_widok(page.route)
        page.update()

    def trasa_zmieniona(e):
        trasa = page.route
        nowy_widok = zbuduj_widok(trasa)
        istniejacy_idx = None
        for i, w in enumerate(page.views):
            if w.route == trasa:
                istniejacy_idx = i
                break
        if istniejacy_idx is not None:
            page.views = page.views[:istniejacy_idx] + [nowy_widok]
        else:
            page.views.append(nowy_widok)
        page.update()

    def widok_zamkniety(e):
        if len(page.views) > 1:
            page.views.pop()
            przejdz(page.views[-1].route)

    # ==========================================
    # WIDOK: EKRAN GŁÓWNY
    # ==========================================
    def zawartosc_main():
        elementy = []
        fab = None
        navbar = None

        if not stan["auto_id"]:
            elementy.append(ft.Text("Witaj we Flocie! Dodaj pojazd używając menu w prawym górnym rogu.", size=16))
            return pasek_glowny(), elementy, fab, navbar

        with polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT oc_data, przeglad_data, nr_rej, vin FROM samochody WHERE id=?", (stan["auto_id"],))
            w = c.fetchone()
        if w:
            def kolor_daty(d_str):
                if not d_str: return ft.Colors.ON_SURFACE_VARIANT, "Brak"
                try:
                    d_obj = datetime.strptime(str(d_str), "%d.%m.%Y").date()
                    roz = (d_obj - datetime.now().date()).days
                    if roz < 0: return ft.Colors.RED_700, f"⚠️ {d_str}"
                    elif roz <= 30: return ft.Colors.ORANGE_700, f"⏳ {d_str}"
                    return ft.Colors.GREEN_700, f"✅ {d_str}"
                except Exception:
                    return ft.Colors.ON_SURFACE_VARIANT, str(d_str)

            k_oc, t_oc = kolor_daty(w[0])
            k_pt, t_pt = kolor_daty(w[1])

            karta_auta = ft.Card(elevation=2, content=ft.Container(border_radius=10, padding=15, content=ft.Column([
                ft.Row([ft.Icon(ft.Icons.BADGE, color=ft.Colors.PRIMARY), ft.Text(str(w[2]) if w[2] else "Brak rej.", weight="bold", size=18)]),
                ft.Text(f"VIN: {str(w[3]) if w[3] else '-'}", size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Divider(height=10),
                ft.Row([ft.Text("OC:", weight="bold", size=13), ft.Text(t_oc, color=k_oc, size=13, weight="bold")], spacing=5),
                ft.Row([ft.Text("PT:", weight="bold", size=13), ft.Text(t_pt, color=k_pt, size=13, weight="bold")], spacing=5)
            ], spacing=5)))
            elementy.append(karta_auta)

        def zmien_zakladke(e):
            stan["zakladka"] = int(e.control.selected_index)
            odswiez_biezacy_widok()

        navbar = ft.NavigationBar(
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.BUILD_CIRCLE_OUTLINED, selected_icon=ft.Icons.BUILD_CIRCLE, label="Serwis"),
                ft.NavigationBarDestination(icon=ft.Icons.LOCAL_GAS_STATION_OUTLINED, selected_icon=ft.Icons.LOCAL_GAS_STATION, label="Paliwo"),
                ft.NavigationBarDestination(icon=ft.Icons.RECEIPT_LONG_OUTLINED, selected_icon=ft.Icons.RECEIPT_LONG, label="Inne"),
                ft.NavigationBarDestination(icon=ft.Icons.PIE_CHART_OUTLINE, selected_icon=ft.Icons.PIE_CHART, label="Statystyki"),
            ],
            on_change=zmien_zakladke,
            selected_index=stan["zakladka"],
        )

        if stan["zakladka"] == 0:
            elementy.append(ft.Row([
                ft.Text("🛠️ Serwis", size=20, weight="bold", color=ft.Colors.PRIMARY, expand=True),
                ft.TextButton("📋 Wizyty Zbiorcze", on_click=lambda e: przejdz("/wizyty"))
            ]))

            opcje_sort_zad = [
                ("Nazwa", "nazwa", lambda r: str(r['nazwa']).lower()),
                ("Ostatnia data", "data", lambda r: parsuj_date(r['data'])),
                ("Przebieg", "przebieg", lambda r: int(r['przebieg'] or 0)),
            ]
            elementy.append(przycisk_sortowania("sort_zadania", opcje_sort_zad))

            akt_prz = int(pobierz_aktualny_przebieg())
            with polacz_baze() as conn:
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                c.execute("SELECT * FROM zadania WHERE auto_id=?", (stan["auto_id"],))
                zadania_lista = c.fetchall()

            posortuj_liste(zadania_lista, "sort_zadania", opcje_sort_zad)

            def pokaz_menu_zadania(zid, zn):
                stan["wybrane_zadanie_id"] = zid
                stan["wybrane_zadanie_nazwa"] = str(zn)

                def zapytaj_usun(ev):
                    zamknij_dno(bs)

                    def wykonaj():
                        with polacz_baze() as con:
                            con.execute("DELETE FROM zadania WHERE id=?", (zid,))
                        odswiez_biezacy_widok()
                        pokaz_komunikat("Usunięto podzespół.")

                    potwierdz(
                        "Usunąć podzespół?",
                        f"Czy na pewno chcesz usunąć „{zn}” wraz z całą historią wymian tej części? Tej operacji nie można cofnąć.",
                        wykonaj,
                    )

                bs = ft.BottomSheet(ft.Container(padding=20, bgcolor=ft.Colors.SURFACE, content=ft.Column([
                    ft.Text(str(zn), weight="bold", size=20, color=ft.Colors.PRIMARY),
                    ft.Divider(),
                    ft.ListTile(leading=ft.Icon(ft.Icons.ADD_CIRCLE, color=ft.Colors.GREEN), title=ft.Text("Dodaj Wymianę / Naprawę", weight="bold"), on_click=lambda e: (zamknij_dno(bs), przejdz(f"/wpis/nowy/{zid}"))),
                    ft.ListTile(leading=ft.Icon(ft.Icons.HISTORY), title=ft.Text("Historia wymian"), on_click=lambda e: (zamknij_dno(bs), przejdz(f"/historia/{zid}"))),
                    ft.ListTile(leading=ft.Icon(ft.Icons.TIMER), title=ft.Text("Ustaw interwał przypomnień"), on_click=lambda e: (zamknij_dno(bs), przejdz(f"/interwal/{zid}"))),
                    ft.ListTile(leading=ft.Icon(ft.Icons.EDIT), title=ft.Text("Zmień nazwę"), on_click=lambda e: (zamknij_dno(bs), przejdz(f"/zadanie/edytuj/{zid}"))),
                    ft.ListTile(leading=ft.Icon(ft.Icons.DELETE, color=ft.Colors.RED), title=ft.Text("Usuń podzespół", color=ft.Colors.RED), on_click=zapytaj_usun),
                ], tight=True)))
                otworz_dno(bs)

            for z in zadania_lista:
                stxt = []
                kol = ft.Colors.GREEN_700
                ico = ft.Icons.CHECK_CIRCLE

                if z['interwal_km'] and z['przebieg']:
                    zost_km = (int(z['przebieg']) + int(z['interwal_km'])) - akt_prz
                    if zost_km < 0:
                        stxt.append(f"{formatuj_liczba(abs(zost_km), 0)} km po!")
                        kol = ft.Colors.RED_700
                        ico = ft.Icons.WARNING
                    elif zost_km <= 1500:
                        stxt.append(f"{formatuj_liczba(zost_km, 0)} km")
                        kol = ft.Colors.ORANGE_700
                        ico = ft.Icons.HOURGLASS_BOTTOM
                    else:
                        stxt.append(f"{formatuj_liczba(zost_km, 0)} km")

                if z['interwal_miesiace'] and z['data']:
                    d_w = parsuj_date(z['data'])
                    if d_w != datetime.min.date():
                        zost_dni = (d_w + timedelta(days=int(float(z['interwal_miesiace'])*30.5)) - datetime.now().date()).days
                        if zost_dni < 0:
                            stxt.append(f"{abs(zost_dni)} dni po!")
                            kol = ft.Colors.RED_700
                            ico = ft.Icons.WARNING
                        elif zost_dni <= 30:
                            stxt.append(f"{zost_dni} dni")
                            if kol != ft.Colors.RED_700:
                                kol = ft.Colors.ORANGE_700
                                ico = ft.Icons.HOURGLASS_BOTTOM
                        else:
                            stxt.append(f"~{zost_dni//30} m-cy")

                if stxt:
                    final_status = " | ".join(stxt)
                else:
                    if not z['interwal_km'] and not z['interwal_miesiace']:
                        final_status = "Brak interwału"
                    else:
                        final_status = "Brak wpisów"
                    kol = ft.Colors.ON_SURFACE_VARIANT
                    ico = ft.Icons.INFO_OUTLINE

                data_w = str(z['data']) if z['data'] else '-'
                prz_w = f"{formatuj_liczba(int(z['przebieg']), 0)} km" if z['przebieg'] else '-'

                karta_z = ft.Card(elevation=1, content=ft.Container(
                    padding=15,
                    on_click=lambda e, zid=z['id'], zn=z['nazwa']: pokaz_menu_zadania(zid, zn),
                    content=ft.Column([
                        ft.Row([ft.Text(str(z['nazwa']), weight="bold", size=16, expand=True), ft.Icon(ico, color=kol)]),
                        ft.Text(f"Wymieniono: {data_w} | Przy: {prz_w}", size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.Text(final_status, size=14, weight="bold", color=kol)
                    ])
                ))
                elementy.append(karta_z)

            fab = ft.FloatingActionButton(icon=ft.Icons.ADD, on_click=lambda e: przejdz("/zadanie/nowy"), bgcolor=ft.Colors.PRIMARY, foreground_color=ft.Colors.ON_PRIMARY)

        elif stan["zakladka"] == 1:
            elementy.append(ft.Text("⛽ Dziennik Tankowań", size=20, weight="bold", color=ft.Colors.PRIMARY))

            opcje_sort_tank = [
                ("Data", "data", lambda x: (parsuj_date(x['data']), x['id'])),
                ("Przebieg", "przebieg", lambda x: int(x['przebieg'] or 0)),
                ("Kwota", "kwota", lambda x: float(x['kwota'] or 0)),
                ("Litry", "litry", lambda x: float(x['litry'] or 0)),
            ]
            elementy.append(przycisk_sortowania("sort_tankowania", opcje_sort_tank))

            with polacz_baze() as conn:
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                c.execute("SELECT * FROM tankowania WHERE auto_id=?", (stan["auto_id"],))
                tankowania_lista = c.fetchall()

            posortuj_liste(tankowania_lista, "sort_tankowania", opcje_sort_tank)

            def menu_t(tid):
                def zapytaj_usun(ev):
                    zamknij_dno(bs)

                    def wykonaj():
                        with polacz_baze() as con:
                            con.execute("DELETE FROM tankowania WHERE id=?", (tid,))
                        odswiez_biezacy_widok()
                        pokaz_komunikat("Usunięto wpis.")

                    potwierdz("Usunąć tankowanie?", "Czy na pewno chcesz usunąć ten wpis tankowania?", wykonaj)

                bs = ft.BottomSheet(ft.Container(padding=20, bgcolor=ft.Colors.SURFACE, content=ft.Column([
                    ft.Text("Opcje wpisu", weight="bold", size=18),
                    ft.ListTile(leading=ft.Icon(ft.Icons.EDIT), title=ft.Text("Edytuj wpis"), on_click=lambda e: (zamknij_dno(bs), przejdz(f"/tankowanie/edytuj/{tid}"))),
                    ft.ListTile(leading=ft.Icon(ft.Icons.DELETE, color=ft.Colors.RED), title=ft.Text("Usuń wpis", color=ft.Colors.RED), on_click=zapytaj_usun),
                ], tight=True)))
                otworz_dno(bs)

            for w in tankowania_lista:
                cena_str = f"{formatuj_liczba(float(w['kwota'] or 0))} zł"
                pelny_txt = "(Pełny)" if w['do_pelna'] else ""
                litry_str = f"{formatuj_liczba(float(w['litry'] or 0))} L {pelny_txt}"

                karta_t = ft.Card(elevation=1, content=ft.Container(
                    padding=15,
                    on_click=lambda e, tid=w['id']: menu_t(tid),
                    content=ft.Column([
                        ft.Row([ft.Text(str(w['data']), weight="bold", size=16), ft.Text(f"-{cena_str}", weight="bold", color=ft.Colors.RED_700)]),
                        ft.Row([ft.Text(litry_str, color=ft.Colors.ON_SURFACE_VARIANT), ft.Text(f"{formatuj_liczba(int(w['przebieg'] or 0), 0)} km", color=ft.Colors.ON_SURFACE_VARIANT)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                    ])
                ))
                elementy.append(karta_t)

            fab = ft.FloatingActionButton(icon=ft.Icons.ADD, on_click=lambda e: przejdz("/tankowanie/nowe"), bgcolor=ft.Colors.PRIMARY, foreground_color=ft.Colors.ON_PRIMARY)

        elif stan["zakladka"] == 2:
            elementy.append(ft.Text("🎫 Inne Koszty", size=20, weight="bold", color=ft.Colors.PRIMARY))

            opcje_sort_inne = [
                ("Data", "data", lambda x: (parsuj_date(x['data']), x['id'])),
                ("Kategoria", "kategoria", lambda x: str(x['kategoria'] or "").lower()),
                ("Kwota", "kwota", lambda x: float(x['kwota'] or 0)),
                ("Nazwa", "nazwa", lambda x: str(x['nazwa'] or "").lower()),
            ]
            elementy.append(przycisk_sortowania("sort_inne", opcje_sort_inne))

            with polacz_baze() as conn:
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                c.execute("SELECT * FROM inne_koszty WHERE auto_id=?", (stan["auto_id"],))
                inne_lista = c.fetchall()

            posortuj_liste(inne_lista, "sort_inne", opcje_sort_inne)

            def otworz_menu_i(iid):
                def zapytaj_usun(ev):
                    zamknij_dno(bs)

                    def wykonaj():
                        with polacz_baze() as con:
                            con.execute("DELETE FROM inne_koszty WHERE id=?", (iid,))
                        odswiez_biezacy_widok()
                        pokaz_komunikat("Usunięto koszt.")

                    potwierdz("Usunąć koszt?", "Czy na pewno chcesz usunąć ten wpis kosztu?", wykonaj)

                bs = ft.BottomSheet(ft.Container(
                    padding=20, bgcolor=ft.Colors.SURFACE,
                    content=ft.Column([
                        ft.Text("Opcje kosztu", weight="bold", size=18),
                        ft.ListTile(leading=ft.Icon(ft.Icons.EDIT), title=ft.Text("Edytuj koszt"), on_click=lambda ev: (zamknij_dno(bs), przejdz(f"/inne/edytuj/{iid}"))),
                        ft.ListTile(leading=ft.Icon(ft.Icons.DELETE, color=ft.Colors.RED), title=ft.Text("Usuń koszt", color=ft.Colors.RED), on_click=zapytaj_usun),
                    ], tight=True)
                ))
                otworz_dno(bs)

            for w in inne_lista:
                cena_str = f"{formatuj_liczba(float(w['kwota'] or 0))} zł"

                karta_i = ft.Card(elevation=1, content=ft.Container(
                    padding=15,
                    on_click=lambda e, iid=w['id']: otworz_menu_i(iid),
                    content=ft.Column([
                        ft.Row([ft.Text(str(w['data']), weight="bold", color=ft.Colors.ON_SURFACE_VARIANT), ft.Text(f"-{cena_str}", weight="bold", color=ft.Colors.RED_700)]),
                        ft.Text(str(w['nazwa']) if w['nazwa'] else "Brak opisu", size=16, weight="bold"),
                        ft.Text(str(w['kategoria']), size=12, color=ft.Colors.ON_SURFACE_VARIANT)
                    ])
                ))
                elementy.append(karta_i)

            fab = ft.FloatingActionButton(icon=ft.Icons.ADD, on_click=lambda e: przejdz("/inne/nowy"), bgcolor=ft.Colors.PRIMARY, foreground_color=ft.Colors.ON_PRIMARY)

        elif stan["zakladka"] == 3:
            with polacz_baze() as conn:
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                c.execute("SELECT * FROM tankowania WHERE auto_id=?", (stan["auto_id"],))
                tankowania = c.fetchall()
                c.execute("SELECT SUM(cena) FROM historia h JOIN zadania z ON h.zadanie_id=z.id WHERE z.auto_id=? AND h.wizyta_id IS NULL", (stan["auto_id"],))
                serw = float(c.fetchone()[0] or 0.0)
                c.execute("SELECT SUM(koszt_calkowity) FROM wizyty WHERE auto_id=?", (stan["auto_id"],))
                serw += float(c.fetchone()[0] or 0.0)
                c.execute("SELECT SUM(kwota) FROM inne_koszty WHERE auto_id=?", (stan["auto_id"],))
                inn = float(c.fetchone()[0] or 0.0)

            tankowania = list(tankowania)
            tankowania.sort(key=lambda x: (parsuj_date(x['data']), x['przebieg']))

            pal = sum(float(t['kwota']) for t in tankowania) if tankowania else 0.0
            litry = sum(float(t['litry']) for t in tankowania) if tankowania else 0.0
            dystans = (int(tankowania[-1]['przebieg']) - int(tankowania[0]['przebieg'])) if len(tankowania) > 1 else 0

            spalanie = 0.0
            peln_idx = [i for i, t in enumerate(tankowania) if t['do_pelna']]
            if len(peln_idx) >= 2:
                p, o = peln_idx[0], peln_idx[-1]
                d_p = int(tankowania[o]['przebieg']) - int(tankowania[p]['przebieg'])
                l_p = sum(float(t['litry']) for t in tankowania[p+1: o+1])
                if d_p > 0:
                    spalanie = (l_p / d_p) * 100

            razem = pal + serw + inn
            koszt_km = (razem / dystans) if dystans > 0 else 0.0

            def kafel_stat(ikona, tytul, wartosc, kolor=ft.Colors.PRIMARY):
                return ft.Card(elevation=1, content=ft.Container(
                    padding=15,
                    content=ft.Row([
                        ft.Icon(ikona, color=kolor, size=30),
                        ft.Column([ft.Text(tytul, size=13, color=ft.Colors.ON_SURFACE_VARIANT), ft.Text(wartosc, weight="bold", size=18)], spacing=0)
                    ])
                ))

            def zmien_podzakladke_stat(idx):
                stan["stat_podzakladka"] = idx
                odswiez_biezacy_widok()

            cur_tab = stan["stat_podzakladka"]

            def przycisk_zakladki(etykieta, idx):
                zaznaczony = cur_tab == idx
                return ft.Button(
                    etykieta,
                    style=ft.ButtonStyle(padding=5),
                    bgcolor=ft.Colors.PRIMARY if zaznaczony else ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE),
                    color=ft.Colors.ON_PRIMARY if zaznaczony else ft.Colors.ON_SURFACE_VARIANT,
                    on_click=lambda e, i=idx: zmien_podzakladke_stat(i),
                    expand=True,
                )

            pasek_przelacznikow = ft.Row([
                przycisk_zakladki("Liczby", 0),
                przycisk_zakladki("Wykresy", 1),
                przycisk_zakladki("Tabele", 2),
            ], spacing=5)

            elementy.append(pasek_przelacznikow)

            if cur_tab == 0:
                elementy.extend([
                    ft.Text("📊 Podsumowanie Kosztów", size=20, weight="bold", color=ft.Colors.PRIMARY),
                    kafel_stat(ft.Icons.ATTACH_MONEY, "Całkowity koszt auta", f"{formatuj_liczba(razem)} zł", ft.Colors.RED_700),
                    kafel_stat(ft.Icons.LOCAL_GAS_STATION, "Wydano na paliwo", f"{formatuj_liczba(pal)} zł"),
                    kafel_stat(ft.Icons.BUILD, "Wydano na serwis", f"{formatuj_liczba(serw)} zł"),
                    kafel_stat(ft.Icons.RECEIPT_LONG, "Inne koszty", f"{formatuj_liczba(inn)} zł"),
                    ft.Text("📈 Wskaźniki i Paliwo", size=20, weight="bold", color=ft.Colors.PRIMARY),
                    kafel_stat(ft.Icons.SPEED, "Średnie spalanie", f"{formatuj_liczba(spalanie)} l/100km" if spalanie > 0 else "Wymaga 2x do pełna", ft.Colors.GREEN_700),
                    kafel_stat(ft.Icons.ADD_ROAD, "Koszt 1 kilometra", f"{formatuj_liczba(koszt_km)} zł/km", ft.Colors.GREEN_700),
                    kafel_stat(ft.Icons.ROUTE, "Zanotowany dystans", f"{formatuj_liczba(dystans, 0)} km"),
                    kafel_stat(ft.Icons.WATER_DROP, "Łącznie zatankowano", f"{formatuj_liczba(litry)} L")
                ])

            elif cur_tab == 1:
                proc_pal = (pal / razem * 100) if razem > 0 else 0
                proc_ser = (serw / razem * 100) if razem > 0 else 0
                proc_inn = (inn / razem * 100) if razem > 0 else 0

                def segment_procentowy(tytul, kwota, procent, kolor):
                    return ft.Column([
                        ft.Row([
                            ft.Text(tytul, weight="bold", size=14),
                            ft.Text(f"{formatuj_liczba(kwota)} zł ({formatuj_liczba(procent, 1)}%)", weight="bold", color=kolor)
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.ProgressBar(value=(procent / 100) if procent > 0 else 0, color=kolor, bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.ON_SURFACE), height=12)
                    ], spacing=4)

                elementy.extend([
                    ft.Text("Struktura Kosztów", weight="bold", size=18, color=ft.Colors.PRIMARY),
                    segment_procentowy("⛽ Paliwo", pal, proc_pal, ft.Colors.BLUE_700),
                    segment_procentowy("🛠️ Serwis i Naprawy", serw, proc_ser, ft.Colors.RED_700),
                    segment_procentowy("🎫 Inne Koszty", inn, proc_inn, ft.Colors.GREEN_700),
                ])

            elif cur_tab == 2:
                miesiace_stat_kwo = {}
                miesiace_stat_lit = {}
                lata_stat_kwo = {}
                lata_stat_lit = {}

                for t in tankowania:
                    d = parsuj_date(t['data'])
                    if d != datetime.min.date():
                        m_key = d.strftime("%Y-%m")
                        r_key = d.strftime("%Y")
                        miesiace_stat_kwo[m_key] = miesiace_stat_kwo.get(m_key, 0) + float(t['kwota'])
                        miesiace_stat_lit[m_key] = miesiace_stat_lit.get(m_key, 0) + float(t['litry'])
                        lata_stat_kwo[r_key] = lata_stat_kwo.get(r_key, 0) + float(t['kwota'])
                        lata_stat_lit[r_key] = lata_stat_lit.get(r_key, 0) + float(t['litry'])

                tabela_mc = ft.DataTable(
                    columns=[
                        ft.DataColumn(ft.Text("Miesiąc")), ft.DataColumn(ft.Text("Koszt")),
                        ft.DataColumn(ft.Text("Litry")), ft.DataColumn(ft.Text("Śr. Cena"))
                    ], rows=[]
                )
                for m in sorted(miesiace_stat_kwo.keys(), reverse=True):
                    wm = miesiace_stat_kwo[m]; l = miesiace_stat_lit[m]
                    sr = wm / l if l > 0 else 0
                    tabela_mc.rows.append(ft.DataRow(cells=[
                        ft.DataCell(ft.Text(m)), ft.DataCell(ft.Text(f"{formatuj_liczba(wm)} zł")),
                        ft.DataCell(ft.Text(f"{formatuj_liczba(l, 1)} L")), ft.DataCell(ft.Text(f"{formatuj_liczba(sr)} zł/l"))
                    ]))

                tabela_lata = ft.DataTable(
                    columns=[
                        ft.DataColumn(ft.Text("Rok")), ft.DataColumn(ft.Text("Koszt")),
                        ft.DataColumn(ft.Text("Litry")), ft.DataColumn(ft.Text("Śr. Cena"))
                    ], rows=[]
                )
                for r in sorted(lata_stat_kwo.keys(), reverse=True):
                    wl = lata_stat_kwo[r]; l = lata_stat_lit[r]
                    sr = wl / l if l > 0 else 0
                    tabela_lata.rows.append(ft.DataRow(cells=[
                        ft.DataCell(ft.Text(r)), ft.DataCell(ft.Text(f"{formatuj_liczba(wl)} zł")),
                        ft.DataCell(ft.Text(f"{formatuj_liczba(l, 1)} L")), ft.DataCell(ft.Text(f"{formatuj_liczba(sr)} zł/l"))
                    ]))

                elementy.extend([
                    ft.Text("Koszty Paliwa (Miesiące)", weight="bold", size=18, color=ft.Colors.PRIMARY),
                    ft.Row([tabela_mc], scroll=ft.ScrollMode.AUTO),
                    ft.Divider(height=20),
                    ft.Text("Koszty Paliwa (Lata)", weight="bold", size=18, color=ft.Colors.PRIMARY),
                    ft.Row([tabela_lata], scroll=ft.ScrollMode.AUTO),
                ])

        return pasek_glowny(), elementy, fab, navbar

    # ==========================================
    # WIDOK: HISTORIA WYMIAN
    # ==========================================
    def zawartosc_historia(z_id):
        with polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT nazwa FROM zadania WHERE id=?", (z_id,))
            w = c.fetchone()
        z_nazwa = str(w[0]) if w else stan["wybrane_zadanie_nazwa"]
        stan["wybrane_zadanie_id"] = z_id
        stan["wybrane_zadanie_nazwa"] = z_nazwa
        czy_opony = "opon" in z_nazwa.lower() or "kół" in z_nazwa.lower()

        elementy = []
        with polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT h.id, h.data, h.przebieg, h.cena, h.wizyta_id, w.koszt_calkowity, h.kategoria FROM historia h LEFT JOIN wizyty w ON h.wizyta_id=w.id WHERE h.zadanie_id=?", (z_id,))
            wpisy = c.fetchall()

        if not wpisy:
            elementy.append(ft.Text("Brak wpisów w historii dla tej części. Kliknij + na dole, aby dodać.", color=ft.Colors.ON_SURFACE_VARIANT))
        else:
            opcje_sort_hist = [
                ("Data", "data", lambda x: (parsuj_date(x[1]), x[0])),
                ("Przebieg", "przebieg", lambda x: int(x[2] or 0)),
                ("Cena", "cena", lambda x: float((x[5] if x[4] else x[3]) or 0)),
            ]
            elementy.append(przycisk_sortowania("sort_historia", opcje_sort_hist))
            posortuj_liste(wpisy, "sort_historia", opcje_sort_hist)

            def otworz_menu_historii(h_id, w_id):
                if w_id:
                    pokaz_komunikat("Ten wpis jest częścią wizyty zbiorczej. Otwórz 'Wizyty Zbiorcze', aby go edytować.", ft.Colors.ORANGE_700)
                    return

                def zapytaj_usun(ev):
                    zamknij_dno(bs)

                    def wykonaj():
                        with polacz_baze() as con:
                            con.execute("DELETE FROM historia WHERE id=?", (h_id,))
                        aktualizuj_najnowszy_wpis(z_id)
                        odswiez_biezacy_widok()
                        pokaz_komunikat("Usunięto wpis.")

                    potwierdz("Usunąć wpis?", "Czy na pewno chcesz usunąć ten wpis historii?", wykonaj)

                bs = ft.BottomSheet(ft.Container(padding=20, bgcolor=ft.Colors.SURFACE, content=ft.Column([
                    ft.Text("Opcje wpisu historii", weight="bold", size=18),
                    ft.ListTile(leading=ft.Icon(ft.Icons.EDIT), title=ft.Text("Edytuj wpis"), on_click=lambda e: (zamknij_dno(bs), przejdz(f"/wpis/edytuj/{h_id}"))),
                    ft.ListTile(leading=ft.Icon(ft.Icons.DELETE, color=ft.Colors.RED), title=ft.Text("Usuń wpis", color=ft.Colors.RED), on_click=zapytaj_usun),
                ], tight=True)))
                otworz_dno(bs)

            for w in wpisy:
                h_id, data, prz, cena, w_id, w_koszt, kategoria = w
                jest_zbiorcza = w_id is not None
                k_str = f"{formatuj_liczba(float(w_koszt) if jest_zbiorcza else float(cena or 0))} zł"
                typ = "Wizyta Zbiorcza" if jest_zbiorcza else "Pojedynczy wpis"

                sub_tekst = f"Przebieg: {formatuj_liczba(int(prz or 0), 0)} km  |  {typ}"
                if czy_opony and kategoria:
                    sub_tekst += f"\nOpony: {kategoria}"

                karta = ft.Card(elevation=1, content=ft.Container(
                    padding=15,
                    on_click=lambda e, hid=h_id, wid=w_id: otworz_menu_historii(hid, wid),
                    content=ft.Column([
                        ft.Row([ft.Text(str(data), weight="bold", size=16), ft.Text(k_str, color=ft.Colors.RED_700, weight="bold")]),
                        ft.Text(sub_tekst, size=13, color=ft.Colors.ON_SURFACE_VARIANT)
                    ])
                ))
                elementy.append(karta)

        appbar = pasek_z_powrotem(f"Historia: {z_nazwa}", "/")
        fab = ft.FloatingActionButton(icon=ft.Icons.ADD, on_click=lambda e: przejdz(f"/wpis/nowy/{z_id}"), bgcolor=ft.Colors.PRIMARY, foreground_color=ft.Colors.ON_PRIMARY)
        return appbar, elementy, fab, None

    # ==========================================
    # WIDOK: WIZYTY ZBIORCZE
    # ==========================================
    def zawartosc_wizyty():
        elementy = []

        opcje_sort_wiz = [
            ("Data", "data", lambda x: (parsuj_date(x[1]), x[0])),
            ("Przebieg", "przebieg", lambda x: int(x[2] or 0)),
            ("Koszt", "koszt", lambda x: float(x[4] or 0)),
            ("Wykonawca", "wykonawca", lambda x: str(x[3] or "").lower()),
        ]
        elementy.append(przycisk_sortowania("sort_wizyty", opcje_sort_wiz))

        with polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT id, data, przebieg, wykonawca, koszt_calkowity FROM wizyty WHERE auto_id=?", (stan["auto_id"],))
            wizyty_lista = c.fetchall()

            posortuj_liste(wizyty_lista, "sort_wizyty", opcje_sort_wiz)

            def otworz_menu_wiz(wid):
                def zapytaj_usun(ev):
                    zamknij_dno(bs)

                    def wykonaj():
                        with polacz_baze() as con:
                            con.execute("DELETE FROM historia WHERE wizyta_id=?", (wid,))
                            con.execute("DELETE FROM wizyty WHERE id=?", (wid,))
                        przelicz_wszystkie_zadania()
                        odswiez_biezacy_widok()
                        pokaz_komunikat("Usunięto wizytę.")

                    potwierdz("Usunąć wizytę?", "Usunięcie wizyty usunie też powiązane wpisy w historii poszczególnych części. Czy kontynuować?", wykonaj)

                bs = ft.BottomSheet(ft.Container(padding=20, bgcolor=ft.Colors.SURFACE, content=ft.Column([
                    ft.Text("Opcje wizyty", weight="bold", size=18),
                    ft.ListTile(leading=ft.Icon(ft.Icons.EDIT), title=ft.Text("Edytuj wizytę"), on_click=lambda e: (zamknij_dno(bs), przejdz(f"/wizyty/edytuj/{wid}"))),
                    ft.ListTile(leading=ft.Icon(ft.Icons.DELETE, color=ft.Colors.RED), title=ft.Text("Usuń wizytę", color=ft.Colors.RED), on_click=zapytaj_usun),
                ], tight=True)))
                otworz_dno(bs)

            for w in wizyty_lista:
                w_id, data, prz, wyk, kosz = w
                c.execute("SELECT z.nazwa FROM historia h JOIN zadania z ON h.zadanie_id=z.id WHERE h.wizyta_id=?", (w_id,))
                czesci = ", ".join([str(r[0]) for r in c.fetchall()])

                karta = ft.Card(elevation=1, content=ft.Container(
                    padding=15,
                    on_click=lambda e, wid=w_id: otworz_menu_wiz(wid),
                    content=ft.Column([
                        ft.Row([ft.Text(str(data), weight="bold", size=16), ft.Text(f"{formatuj_liczba(float(kosz or 0))} zł", color=ft.Colors.RED_700, weight="bold")]),
                        ft.Text(f"Przebieg: {formatuj_liczba(int(prz or 0), 0)} km  |  Mechanik: {str(wyk) if wyk else '-'}", size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.Text(f"Części: {czesci}", size=13, color=ft.Colors.PRIMARY)
                    ])
                ))
                elementy.append(karta)

        appbar = pasek_z_powrotem("Wizyty Zbiorcze", "/")
        fab = ft.FloatingActionButton(icon=ft.Icons.ADD, on_click=lambda e: przejdz("/wizyty/nowa"), bgcolor=ft.Colors.PRIMARY, foreground_color=ft.Colors.ON_PRIMARY)
        return appbar, elementy, fab, None

    # ==========================================
    # WIDOK: FORMULARZ POJAZDU
    # ==========================================
    def zawartosc_form_auto(auto_id):
        n_val, r_val, v_val, ro_val, oc_val, pt_val = "", "", "", "", "", ""
        if auto_id:
            with polacz_baze() as c:
                cur = c.cursor()
                cur.execute("SELECT nazwa, nr_rej, vin, rok_produkcji, oc_data, przeglad_data FROM samochody WHERE id=?", (auto_id,))
                w = cur.fetchone()
                if w:
                    n_val, r_val, v_val = str(w[0] or ""), str(w[1] or ""), str(w[2] or "")
                    ro_val, oc_val, pt_val = str(w[3] or ""), str(w[4] or ""), str(w[5] or "")

        e_nazwa = ft.TextField(label="Nazwa pojazdu (Główna)*", value=n_val)
        e_rej = ft.TextField(label="Nr Rejestracyjny", value=r_val)
        e_rok = ft.TextField(label="Rok produkcji", value=ro_val, input_filter=FILTR_CALKOWITY, keyboard_type=ft.KeyboardType.NUMBER)
        e_vin = ft.TextField(label="VIN", value=v_val)
        e_oc = pole_daty("Polisa OC", oc_val)
        e_pt = pole_daty("Przegląd techniczny", pt_val)

        def zapisz_auto(e):
            for pole in (e_nazwa, e_rok, e_vin):
                pole.error_text = None

            n = (e_nazwa.value or "").strip()
            bledy = []
            if not n:
                bledy.append((e_nazwa, "Podaj nazwę pojazdu"))

            rok_txt = (e_rok.value or "").strip()
            rok_obecny = datetime.now().year
            if rok_txt:
                rok_num = parsuj_int(rok_txt, None)
                if rok_num is None or rok_num < ROK_MIN or rok_num > rok_obecny + 1:
                    bledy.append((e_rok, f"Podaj poprawny rok ({ROK_MIN}–{rok_obecny + 1})"))

            vin_txt = (e_vin.value or "").strip()
            if vin_txt and len(vin_txt) > 17:
                bledy.append((e_vin, "VIN nie powinien mieć więcej niż 17 znaków"))

            if bledy:
                pokaz_bledy_formularza(bledy)
                return

            try:
                with polacz_baze() as conn:
                    if auto_id:
                        conn.execute("UPDATE samochody SET nazwa=?, nr_rej=?, vin=?, rok_produkcji=?, oc_data=?, przeglad_data=? WHERE id=?",
                                     (n, e_rej.value, e_vin.value, e_rok.value, e_oc.value, e_pt.value, auto_id))
                    else:
                        cur = conn.cursor()
                        cur.execute("INSERT INTO samochody (nazwa, nr_rej, vin, rok_produkcji, oc_data, przeglad_data) VALUES (?,?,?,?,?,?)",
                                    (n, e_rej.value, e_vin.value, e_rok.value, e_oc.value, e_pt.value))
                        n_id = cur.lastrowid
                        for dz in DOMYSLNE_ZADANIA:
                            conn.execute("INSERT INTO zadania (auto_id, nazwa) VALUES (?, ?)", (n_id, dz))
                        stan["auto_id"] = n_id

                przejdz("/")
                pokaz_komunikat("Zapisano pojazd!")
            except sqlite3.IntegrityError:
                e_nazwa.error_text = "Pojazd o takiej nazwie już istnieje!"
                page.update()

        elementy = [
            e_nazwa, e_rej, e_rok, e_vin, e_oc, e_pt,
            ft.Button("✅ Zapisz pojazd", on_click=zapisz_auto, bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE, width=float("inf"), height=48),
            ft.OutlinedButton("Anuluj", on_click=lambda e: przejdz("/"), width=float("inf"), height=45)
        ]
        appbar = pasek_z_powrotem("Edycja pojazdu" if auto_id else "Nowy pojazd", "/")
        return appbar, elementy, None, None

    # ==========================================
    # WIDOK: FORMULARZ TANKOWANIA
    # ==========================================
    def zawartosc_form_tankowanie(t_id):
        d_val = datetime.now().strftime("%d.%m.%Y")
        p_val = str(pobierz_aktualny_przebieg() or "")
        dys_val, l_val, k_val, pelna_val = "", "", "", True

        if t_id:
            with polacz_baze() as conn:
                c = conn.cursor()
                c.execute("SELECT data, przebieg, dystans, litry, kwota, do_pelna FROM tankowania WHERE id=?", (t_id,))
                w = c.fetchone()
                if w:
                    d_val, p_val, dys_val = str(w[0] or ""), str(w[1] or ""), str(w[2] or "")
                    l_val, k_val, pelna_val = str(w[3] or ""), str(w[4] or ""), bool(w[5])

        e_d = pole_daty("Data", d_val)
        e_p = ft.TextField(label="Stan licznika (km)", value=p_val, keyboard_type=ft.KeyboardType.NUMBER, input_filter=FILTR_CALKOWITY)
        e_dys = ft.TextField(label="LUB Dystans (km)", value=dys_val, keyboard_type=ft.KeyboardType.NUMBER, input_filter=FILTR_CALKOWITY)
        e_l = ft.TextField(label="Litry", value=l_val, keyboard_type=ft.KeyboardType.NUMBER, input_filter=FILTR_DZIESIETNY)
        e_k = ft.TextField(label="Koszt (zł)", value=k_val, keyboard_type=ft.KeyboardType.NUMBER, input_filter=FILTR_DZIESIETNY)
        c_pel = ft.Checkbox(label="Zatankowano do pełna (do spalania)", value=pelna_val)

        def zapisz_tankowanie(e):
            for pole in (e_p, e_dys, e_l, e_k):
                pole.error_text = None

            prz = parsuj_int(e_p.value, 0)
            dys = parsuj_float(e_dys.value, 0.0)
            lit = parsuj_float(e_l.value, 0.0)
            kwo = parsuj_float(e_k.value, 0.0)

            bledy = []
            if lit <= 0:
                bledy.append((e_l, "Podaj liczbę litrów większą od zera"))
            if kwo <= 0:
                bledy.append((e_k, "Podaj kwotę większą od zera"))
            if prz <= 0 and dys <= 0:
                bledy.append((e_p, "Podaj stan licznika lub przejechany dystans"))
            if bledy:
                pokaz_bledy_formularza(bledy)
                return

            ostatni_prz = 0
            with polacz_baze() as conn:
                c = conn.cursor()
                if t_id:
                    c.execute("SELECT MAX(przebieg) FROM tankowania WHERE auto_id=? AND id!=?", (stan["auto_id"], t_id))
                else:
                    c.execute("SELECT MAX(przebieg) FROM tankowania WHERE auto_id=?", (stan["auto_id"],))
                res = c.fetchone()
                if res and res[0]:
                    ostatni_prz = int(res[0])

            if prz == 0 and dys > 0:
                prz = int(ostatni_prz + dys)
            elif dys == 0.0 and prz > 0:
                dys = float(prz - ostatni_prz) if prz > ostatni_prz else 0.0

            if ostatni_prz and prz < ostatni_prz:
                pokaz_komunikat(f"Uwaga: podany przebieg jest niższy niż ostatnio zanotowany ({formatuj_liczba(ostatni_prz, 0)} km).", ft.Colors.ORANGE_700)

            with polacz_baze() as conn:
                do_pel = 1 if c_pel.value else 0
                if t_id:
                    conn.execute("UPDATE tankowania SET data=?, przebieg=?, dystans=?, litry=?, kwota=?, do_pelna=? WHERE id=?",
                                 (e_d.value, prz, dys, lit, kwo, do_pel, t_id))
                else:
                    conn.execute("INSERT INTO tankowania (auto_id, data, przebieg, dystans, litry, kwota, do_pelna) VALUES (?,?,?,?,?,?,?)",
                                 (stan["auto_id"], e_d.value, prz, dys, lit, kwo, do_pel))

            przelicz_wszystkie_zadania()
            przejdz("/")
            pokaz_komunikat("Zapisano tankowanie!")

        elementy = [
            e_d, e_p, e_dys, e_l, e_k, c_pel,
            ft.Button("✅ Zapisz tankowanie", on_click=zapisz_tankowanie, bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE, width=float("inf"), height=48),
            ft.OutlinedButton("Anuluj", on_click=lambda e: przejdz("/"), width=float("inf"), height=45)
        ]
        appbar = pasek_z_powrotem("Edycja tankowania" if t_id else "Nowe tankowanie", "/")
        return appbar, elementy, None, None

    # ==========================================
    # WIDOK: FORMULARZ INNEGO KOSZTU
    # ==========================================
    def zawartosc_form_inne(i_id):
        d_val = datetime.now().strftime("%d.%m.%Y")
        k_val, op_val, kw_val = KATEGORIE_INNE[0], "", ""
        if i_id:
            with polacz_baze() as conn:
                c = conn.cursor()
                c.execute("SELECT data, kategoria, nazwa, kwota FROM inne_koszty WHERE id=?", (i_id,))
                w = c.fetchone()
                if w:
                    d_val, k_val = str(w[0] or ""), str(w[1] or "")
                    op_val, kw_val = str(w[2] or ""), str(w[3] or "")

        e_d = pole_daty("Data", d_val)
        e_k = ft.Dropdown(label="Kategoria", options=[ft.DropdownOption(key=x, text=x) for x in KATEGORIE_INNE], value=k_val)
        e_o = ft.TextField(label="Opis / Nazwa", value=op_val)
        e_kw = ft.TextField(label="Kwota (zł)", value=kw_val, keyboard_type=ft.KeyboardType.NUMBER, input_filter=FILTR_DZIESIETNY)

        def zapisz_inne(e):
            for pole in (e_o, e_kw):
                pole.error_text = None

            opis = (e_o.value or "").strip()
            kwo = parsuj_float(e_kw.value, 0.0)

            bledy = []
            if not opis:
                bledy.append((e_o, "Podaj opis / nazwę kosztu"))
            if kwo <= 0:
                bledy.append((e_kw, "Podaj kwotę większą od zera"))
            if bledy:
                pokaz_bledy_formularza(bledy)
                return

            with polacz_baze() as conn:
                if i_id:
                    conn.execute("UPDATE inne_koszty SET data=?, kategoria=?, nazwa=?, kwota=? WHERE id=?",
                                 (e_d.value, e_k.value, opis, kwo, i_id))
                else:
                    conn.execute("INSERT INTO inne_koszty (auto_id, data, kategoria, nazwa, kwota) VALUES (?,?,?,?,?)",
                                 (stan["auto_id"], e_d.value, e_k.value, opis, kwo))
            przejdz("/")
            pokaz_komunikat("Zapisano koszt!")

        elementy = [
            e_d, e_k, e_o, e_kw,
            ft.Button("✅ Zapisz koszt", on_click=zapisz_inne, bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE, width=float("inf"), height=48),
            ft.OutlinedButton("Anuluj", on_click=lambda e: przejdz("/"), width=float("inf"), height=45)
        ]
        appbar = pasek_z_powrotem("Edycja kosztu" if i_id else "Nowy koszt", "/")
        return appbar, elementy, None, None

    # ==========================================
    # WIDOK: FORMULARZ WPISU HISTORII
    # ==========================================
    def zawartosc_form_wpis(h_id, z_id_param):
        if h_id:
            with polacz_baze() as conn:
                c = conn.cursor()
                c.execute("SELECT zadanie_id FROM historia WHERE id=?", (h_id,))
                w = c.fetchone()
                z_id = w[0] if w else z_id_param
        else:
            z_id = z_id_param

        nazwa = ""
        if z_id:
            with polacz_baze() as conn:
                c = conn.cursor()
                c.execute("SELECT nazwa FROM zadania WHERE id=?", (z_id,))
                w = c.fetchone()
                nazwa = str(w[0]) if w else ""

        stan["wybrane_zadanie_id"] = z_id
        stan["wybrane_zadanie_nazwa"] = nazwa
        czy_opony = "opon" in nazwa.lower() or "kół" in nazwa.lower()

        d_val = datetime.now().strftime("%d.%m.%Y")
        p_val = str(pobierz_aktualny_przebieg() or "")
        c_val, w_val, kat_val = "", "", "Letnie"

        if h_id:
            with polacz_baze() as conn:
                c = conn.cursor()
                c.execute("SELECT data, przebieg, cena, wykonawca, kategoria FROM historia WHERE id=?", (h_id,))
                w = c.fetchone()
                if w:
                    d_val, p_val = str(w[0] or ""), str(w[1] or "")
                    c_val, w_val = str(w[2] or ""), str(w[3] or "")
                    if czy_opony and w[4]:
                        kat_val = str(w[4])

        e_d = pole_daty("Data", d_val)
        e_p = ft.TextField(label="Przebieg (km)", value=p_val, keyboard_type=ft.KeyboardType.NUMBER, input_filter=FILTR_CALKOWITY)
        e_c = ft.TextField(label="Koszt robocizny i części (zł)", value=c_val, keyboard_type=ft.KeyboardType.NUMBER, input_filter=FILTR_DZIESIETNY)
        e_w = ft.TextField(label="Wykonawca / Warsztat", value=w_val)
        e_kat = ft.Dropdown(label="Rodzaj opon", options=[ft.DropdownOption(key="Letnie", text="Letnie"), ft.DropdownOption(key="Zimowe", text="Zimowe"), ft.DropdownOption(key="Całoroczne", text="Całoroczne")], value=kat_val, visible=czy_opony)

        trasa_powrotu = f"/historia/{z_id}" if z_id else "/"

        def zapisz_wpis(e):
            for pole in (e_p, e_c):
                pole.error_text = None

            bledy = []
            if not (e_p.value or "").strip():
                bledy.append((e_p, "Podaj przebieg"))
            prz = parsuj_int(e_p.value, 0)
            if prz < 0:
                bledy.append((e_p, "Przebieg nie może być ujemny"))

            kos = parsuj_float(e_c.value, 0.0)
            if kos < 0:
                bledy.append((e_c, "Koszt nie może być ujemny"))

            if bledy:
                pokaz_bledy_formularza(bledy)
                return

            wyk = e_w.value or "Warsztat"
            kat = e_kat.value if czy_opony else None

            with polacz_baze() as conn:
                if h_id:
                    conn.execute("UPDATE historia SET data=?, przebieg=?, cena=?, wykonawca=?, kategoria=? WHERE id=?",
                                 (e_d.value, prz, kos, wyk, kat, h_id))
                else:
                    conn.execute("INSERT INTO historia (zadanie_id, data, przebieg, cena, wykonawca, kategoria) VALUES (?,?,?,?,?,?)",
                                 (z_id, e_d.value, prz, kos, wyk, kat))

            aktualizuj_najnowszy_wpis(z_id)
            przejdz(trasa_powrotu)
            pokaz_komunikat("Zapisano wpis!")

        elementy = [
            e_d, e_p, e_kat, e_c, e_w,
            ft.Button("✅ Zapisz wymianę", on_click=zapisz_wpis, bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE, width=float("inf"), height=48),
            ft.OutlinedButton("Anuluj", on_click=lambda e: przejdz(trasa_powrotu), width=float("inf"), height=45)
        ]
        appbar = pasek_z_powrotem(f"{'Edycja' if h_id else 'Nowa wymiana'}: {nazwa}", trasa_powrotu)
        return appbar, elementy, None, None

    # ==========================================
    # WIDOK: FORMULARZ WIZYTY ZBIORCZEJ
    # ==========================================
    def zawartosc_form_wizyty(w_id):
        d_val = datetime.now().strftime("%d.%m.%Y")
        p_val = str(pobierz_aktualny_przebieg() or "")
        wyk_val, kosz_val, not_val = "", "", ""
        podpiete = set()

        if w_id:
            with polacz_baze() as conn:
                c = conn.cursor()
                c.execute("SELECT data, przebieg, wykonawca, koszt_calkowity, notatki FROM wizyty WHERE id=?", (w_id,))
                w = c.fetchone()
                if w:
                    d_val, p_val = str(w[0] or ""), str(w[1] or "")
                    wyk_val, kosz_val, not_val = str(w[2] or ""), str(w[3] or "")
                c.execute("SELECT zadanie_id FROM historia WHERE wizyta_id=?", (w_id,))
                podpiete = {r[0] for r in c.fetchall()}

        e_d = pole_daty("Data", d_val)
        e_p = ft.TextField(label="Przebieg (km)", value=p_val, keyboard_type=ft.KeyboardType.NUMBER, input_filter=FILTR_CALKOWITY)
        e_w = ft.TextField(label="Wykonawca", value=wyk_val)
        e_k = ft.TextField(label="Łączny koszt (zł)", value=kosz_val, keyboard_type=ft.KeyboardType.NUMBER, input_filter=FILTR_DZIESIETNY)
        e_n = ft.TextField(label="Notatki", value=not_val)
        blad_czesci = ft.Text("", color=ft.Colors.RED_700, size=13)

        chk_czesci = []
        with polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT id, nazwa FROM zadania WHERE auto_id=? ORDER BY nazwa", (stan["auto_id"],))
            for z_i, z_n in c.fetchall():
                chk_czesci.append(ft.Checkbox(label=str(z_n), value=(z_i in podpiete), data=z_i))

        def zapisz_wizyte(e):
            for pole in (e_p, e_k):
                pole.error_text = None
            blad_czesci.value = ""

            bledy = []
            prz = parsuj_int(e_p.value, 0)
            if not (e_p.value or "").strip():
                bledy.append((e_p, "Podaj przebieg"))
            kos = parsuj_float(e_k.value, 0.0)
            if kos < 0:
                bledy.append((e_k, "Koszt nie może być ujemny"))

            wybrane = [chk.data for chk in chk_czesci if chk.value]
            if not wybrane:
                blad_czesci.value = "Zaznacz co najmniej jedną część!"

            if bledy or blad_czesci.value:
                if blad_czesci.value:
                    page.update()
                    pokaz_komunikat("Popraw zaznaczone pola formularza.", ft.Colors.RED_700)
                if bledy:
                    pokaz_bledy_formularza(bledy)
                return

            wyk = e_w.value or "Warsztat"
            with polacz_baze() as conn:
                cur = conn.cursor()
                if w_id:
                    cur.execute("UPDATE wizyty SET data=?, przebieg=?, wykonawca=?, koszt_calkowity=?, notatki=? WHERE id=?",
                                (e_d.value, prz, wyk, kos, e_n.value, w_id))
                    cur.execute("DELETE FROM historia WHERE wizyta_id=?", (w_id,))
                    for zid in wybrane:
                        cur.execute("INSERT INTO historia (wizyta_id, zadanie_id, data, przebieg, cena, wykonawca) VALUES (?,?,?,?,0,?)",
                                    (w_id, zid, e_d.value, prz, wyk))
                else:
                    cur.execute("INSERT INTO wizyty (auto_id, data, przebieg, wykonawca, koszt_calkowity, notatki) VALUES (?,?,?,?,?,?)",
                                (stan["auto_id"], e_d.value, prz, wyk, kos, e_n.value))
                    nw_id = cur.lastrowid
                    for zid in wybrane:
                        cur.execute("INSERT INTO historia (wizyta_id, zadanie_id, data, przebieg, cena, wykonawca) VALUES (?,?,?,?,0,?)",
                                    (nw_id, zid, e_d.value, prz, wyk))

            przelicz_wszystkie_zadania()
            przejdz("/wizyty")
            pokaz_komunikat("Zapisano wizytę zbiorczą!")

        elementy = [
            e_d, e_p, e_w, e_k, e_n,
            ft.Text("Wymienione podzespoły:", weight="bold", color=ft.Colors.PRIMARY),
            ft.Column(chk_czesci, spacing=2),
            blad_czesci,
            ft.Button("✅ Zapisz wizytę", on_click=zapisz_wizyte, bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE, width=float("inf"), height=48),
            ft.OutlinedButton("Anuluj", on_click=lambda e: przejdz("/wizyty"), width=float("inf"), height=45)
        ]
        appbar = pasek_z_powrotem("Edycja wizyty" if w_id else "Nowa wizyta zbiorcza", "/wizyty")
        return appbar, elementy, None, None

    # ==========================================
    # WIDOK: FORMULARZ INTERWAŁU
    # ==========================================
    def zawartosc_form_interwal(z_id):
        nazwa = ""
        ik, im = "", ""
        with polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT nazwa, interwal_km, interwal_miesiace FROM zadania WHERE id=?", (z_id,))
            w = c.fetchone()
            if w:
                nazwa = str(w[0])
                ik, im = str(w[1] or ""), str(w[2] or "")
        stan["wybrane_zadanie_id"] = z_id
        stan["wybrane_zadanie_nazwa"] = nazwa

        e_ik = ft.TextField(label="Co ile km", value=ik, keyboard_type=ft.KeyboardType.NUMBER, input_filter=FILTR_CALKOWITY)
        e_im = ft.TextField(label="Co ile miesięcy", value=im, keyboard_type=ft.KeyboardType.NUMBER, input_filter=FILTR_CALKOWITY)

        def zapisz_interwal(e):
            for pole in (e_ik, e_im):
                pole.error_text = None

            km_txt = (e_ik.value or "").strip()
            mc_txt = (e_im.value or "").strip()

            bledy = []
            vk = None
            vm = None
            if km_txt:
                vk = parsuj_int(km_txt, None)
                if vk is None or vk <= 0:
                    bledy.append((e_ik, "Podaj liczbę całkowitą większą od zera"))
            if mc_txt:
                vm = parsuj_int(mc_txt, None)
                if vm is None or vm <= 0:
                    bledy.append((e_im, "Podaj liczbę całkowitą większą od zera"))
            if not km_txt and not mc_txt:
                bledy.append((e_ik, "Podaj co najmniej jeden interwał (km lub miesiące)"))

            if bledy:
                pokaz_bledy_formularza(bledy)
                return

            with polacz_baze() as conn:
                conn.execute("UPDATE zadania SET interwal_km=?, interwal_miesiace=? WHERE id=?", (vk, vm, z_id))
            przejdz("/")
            pokaz_komunikat("Zapisano interwały.")

        def usun_interwal(e):
            with polacz_baze() as conn:
                conn.execute("UPDATE zadania SET interwal_km=NULL, interwal_miesiace=NULL WHERE id=?", (z_id,))
            przejdz("/")
            pokaz_komunikat("Usunięto przypomnienie.")

        elementy = [
            ft.Text("Ustaw przypomnienia o wymianie:", color=ft.Colors.ON_SURFACE_VARIANT),
            e_ik, e_im,
            ft.Button("✅ Zapisz interwały", on_click=zapisz_interwal, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY, width=float("inf"), height=48),
            ft.OutlinedButton("Wyczyść przypomnienia", on_click=usun_interwal, width=float("inf"), height=45),
            ft.OutlinedButton("Anuluj", on_click=lambda e: przejdz("/"), width=float("inf"), height=45)
        ]
        appbar = pasek_z_powrotem(f"⏱️ Przypomnienia: {nazwa}", "/")
        return appbar, elementy, None, None

    # ==========================================
    # WIDOK: FORMULARZ PODZESPOŁU (ZADANIA)
    # ==========================================
    def zawartosc_form_zadanie(z_id):
        stara_nazwa = ""
        if z_id:
            with polacz_baze() as conn:
                c = conn.cursor()
                c.execute("SELECT nazwa FROM zadania WHERE id=?", (z_id,))
                w = c.fetchone()
                if w:
                    stara_nazwa = str(w[0])
        stan["wybrane_zadanie_nazwa"] = stara_nazwa

        e_n = ft.TextField(label="Nazwa podzespołu", value=stara_nazwa)

        def zapisz_zad(e):
            e_n.error_text = None
            nazwa = (e_n.value or "").strip()
            if not nazwa:
                pokaz_bledy_formularza([(e_n, "Podaj nazwę podzespołu")])
                return

            with polacz_baze() as conn:
                c = conn.cursor()
                c.execute("SELECT id FROM zadania WHERE auto_id=? AND LOWER(nazwa)=LOWER(?) AND id!=?",
                          (stan["auto_id"], nazwa, z_id or 0))
                if c.fetchone():
                    pokaz_bledy_formularza([(e_n, "Podzespół o tej nazwie już istnieje")])
                    return

                if z_id:
                    conn.execute("UPDATE zadania SET nazwa=? WHERE id=?", (nazwa, z_id))
                else:
                    conn.execute("INSERT INTO zadania (auto_id, nazwa) VALUES (?,?)", (stan["auto_id"], nazwa))
            przejdz("/")
            pokaz_komunikat("Zapisano podzespół!")

        elementy = [
            e_n,
            ft.Button("✅ Zapisz", on_click=zapisz_zad, bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE, width=float("inf"), height=48),
            ft.OutlinedButton("Anuluj", on_click=lambda e: przejdz("/"), width=float("inf"), height=45)
        ]
        appbar = pasek_z_powrotem("Edycja pozycji" if z_id else "Nowa pozycja", "/")
        return appbar, elementy, None, None

    # ==========================================
    # URUCHOMIENIE APLIKACJI
    # ==========================================
    page.on_route_change = trasa_zmieniona
    page.on_view_pop = widok_zamkniety

    zainicjuj_domyslne_auto()
    przejdz(page.route or "/")

# NOWA FUNKCJA URUCHAMIAJĄCA (zamiast ft.app)
ft.run(main)