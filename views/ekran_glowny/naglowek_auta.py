"""Karta pojazdu nad zakładkami: zdjęcie, terminy, kondycja i szybkie akcje."""

import db
import flet as ft
import sqlite3
import utils


class MiksinNaglowkaAuta:
    """Karta pojazdu nad zakładkami: zdjęcie, terminy, kondycja i szybkie akcje."""

    # ================= KOMPAKTOWA KARTA POJAZDU =================
    def buduj_naglowek_auta(self):
        with db.polacz_baze() as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            # Sprzedane auta wypadają z przełącznika i showroomu — garaż ma
            # pokazywać to, czym się jeździ. Ich historia zostaje dostępna
            # z ekranu Archiwum (patrz db.pobierz_sprzedane_pojazdy).
            c.execute(f"SELECT id, nazwa FROM samochody WHERE {db.WARUNEK_AKTYWNE} ORDER BY nazwa")
            auta = c.fetchall()
            c.execute("SELECT nr_rej, zdjecie_glowne, wiadomosc_statusu FROM samochody WHERE id=?", (self.state.auto_id,))
            w = c.fetchone()

        if not w: return

        wiadomosc_statusu = w["wiadomosc_statusu"]
        aktualny_przebieg = db.pobierz_aktualny_przebieg(self.state.auto_id)

        # Komplet danych pojazdu liczony RAZ: kafel pokazuje teraz także wiek,
        # tablicę i najbliższy termin, a każde z osobnego zapytania robiłoby
        # z jednej karty cztery odpytania bazy przy każdym wejściu na ekran.
        dane_pojazdu = db.pobierz_dane_pojazdu(self.state.auto_id) or {}
        metryki_pojazdu = db.pobierz_metryki_pojazdu(self.state.auto_id, dane_pojazdu) or {}
        najblizszy_termin = db.najblizszy_termin_pojazdu(self.state.auto_id, dane_pojazdu)

        # Podgląd sprzedanego auta otwiera się z Archiwum przez podstawienie
        # state.auto_id. Takiego pojazdu NIE MA na liście `auta`, więc strzałki
        # „poprzedni/następny” prowadziłyby w losowe miejsce, a przy garażu
        # złożonym z samych sprzedanych aut lista byłaby pusta i modulo poleciałoby
        # dzieleniem przez zero. Dlatego przy archiwalnym pojeździe karuzeli nie ma.
        czy_sprzedany = str(dane_pojazdu.get("status") or "aktywny") == db.STATUS_POJAZDU_SPRZEDANY

        idx = 0
        for i, a in enumerate(auta):
            if a[0] == self.state.auto_id:
                idx = i
                break

        if auta:
            poprzedni_id, poprzedni_nazwa = auta[(idx - 1) % len(auta)]
            nastepny_id, nastepny_nazwa = auta[(idx + 1) % len(auta)]
        else:
            poprzedni_id, poprzedni_nazwa = self.state.auto_id, self.state.auto_nazwa
            nastepny_id, nastepny_nazwa = self.state.auto_id, self.state.auto_nazwa

        def on_prev(e):
            self.state.auto_id = poprzedni_id
            self.state.auto_nazwa = str(poprzedni_nazwa)
            utils.przejdz(self._page, "/")

        def on_next(e):
            self.state.auto_id = nastepny_id
            self.state.auto_nazwa = str(nastepny_nazwa)
            utils.przejdz(self._page, "/")

        def pokaz_wybor_aut(e):
            """Showroom zamiast listy plików: siatka kart ze zdjęciami pojazdów.
            Auto rozpoznaje się po miniaturze szybciej, niż po przeczytaniu
            nazwy w wierszu listy — przy kilku pojazdach wybór to jedno
            spojrzenie, a nie skanowanie tekstu."""
            with db.polacz_baze() as conn:
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                c.execute(
                    "SELECT id, nazwa, nr_rej, zdjecie_glowne, nadwozie, kolor_motywu, marka, model "
                    f"FROM samochody WHERE {db.WARUNEK_AKTYWNE} ORDER BY nazwa"
                )
                auta_siatki = c.fetchall()

            bs = ft.BottomSheet(ft.Container())
            karty_aut = {}  # id -> (ramka, odznaka)

            # Dwie kolumny na telefonie, trzy na szerokim ekranie. Miniatura musi
            # zostać na tyle duża, żeby dało się rozpoznać auto bez czytania nazwy.
            try:
                szer_ekranu = self._page.width or getattr(self._page.window, "width", None) or 400
            except Exception:
                szer_ekranu = 400
            KOLUMNY = 3 if szer_ekranu >= 620 else 2
            SZER_KARTY = max(128, int((szer_ekranu - 2 * 20 - (KOLUMNY - 1) * 10) / KOLUMNY))
            WYS_ZDJECIA = int(SZER_KARTY * 0.62)

            def wybierz(aid, an):
                for k_aid, (ramka, odznaka) in karty_aut.items():
                    zazn = (k_aid == aid)
                    ramka.border = ft.Border.all(2, ft.Colors.PRIMARY if zazn else ft.Colors.TRANSPARENT)
                    odznaka.visible = zazn

                try:
                    self._page.update()
                except Exception:
                    pass

                self.state.auto_id = aid
                self.state.auto_nazwa = str(an)
                utils.zamknij_dno(self._page, bs)
                utils.przejdz(self._page, "/")

            def dodaj():
                utils.zamknij_dno(self._page, bs)
                utils.przejdz(self._page, "/auto/nowy")

            def zastepcze_zdjecie(a=None):
                """Pojazd bez zdjęcia (albo ze zdjęciem, którego nie ma już na
                dysku) nie może wypaść z siatki — dostaje kafelek z sylwetką
                nadwozia w kolorze przypisanym do TEGO auta, więc karta zachowuje
                ten sam rozmiar i rytm, a auta nadal różnią się od siebie."""
                kolor = utils.MAPA_KOLOROW.get((a["kolor_motywu"] if a is not None else None) or "", ft.Colors.PRIMARY)
                nadwozie = a["nadwozie"] if a is not None else None
                return ft.Container(
                    width=SZER_KARTY, height=WYS_ZDJECIA,
                    bgcolor=ft.Colors.with_opacity(0.10, kolor),
                    alignment=ft.Alignment.CENTER,
                    content=ft.Icon(
                        utils.ikona_nadwozia(nadwozie), size=42,
                        color=ft.Colors.with_opacity(0.60, kolor)
                    ),
                )

            def karta_auta(a):
                a_id, a_nazwa = a["id"], a["nazwa"]
                zaznaczone = (a_id == self.state.auto_id)

                ma_zdjecie = bool(a["zdjecie_glowne"])
                if ma_zdjecie:
                    miniatura = ft.Image(
                        src=utils.abs_zalacznik(a["zdjecie_glowne"]),
                        width=SZER_KARTY, height=WYS_ZDJECIA, fit="cover",
                        error_content=zastepcze_zdjecie(a),
                    )
                else:
                    miniatura = zastepcze_zdjecie(a)

                odznaka = ft.Container(
                    top=6, right=6, visible=zaznaczone,
                    width=24, height=24, border_radius=12,
                    bgcolor=ft.Colors.PRIMARY, alignment=ft.Alignment.CENTER,
                    content=ft.Icon(ft.Icons.CHECK, size=15, color=ft.Colors.ON_PRIMARY),
                )

                # Przy zdjęciu sylwetka schodzi do rogu jako mała plakietka —
                # zdjęcie i tak rozpoznaje auto, ale kolor odznaki utrzymuje
                # ten sam „klucz” wizualny na całej liście.
                plakietka = ft.Container(
                    bottom=6, left=6, visible=ma_zdjecie,
                    content=utils.odznaka_pojazdu(a, rozmiar=26),
                )

                ramka = ft.Container(
                    width=SZER_KARTY,
                    border_radius=utils.RADIUS["md"],
                    border=ft.Border.all(2, ft.Colors.PRIMARY if zaznaczone else ft.Colors.TRANSPARENT),
                    bgcolor=utils.tlo_karty(self._page, poziom=2),
                    clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                    tooltip=str(a_nazwa),
                    on_click=lambda ev, aid=a_id, an=a_nazwa: wybierz(aid, an),
                    content=ft.Column([
                        ft.Stack([miniatura, plakietka, odznaka], width=SZER_KARTY, height=WYS_ZDJECIA),
                        ft.Container(
                            padding=ft.Padding(8, 6, 8, 8),
                            content=ft.Column([
                                ft.Text(
                                    str(a_nazwa), size=utils.FS["body_strong"], weight="bold",
                                    no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS,
                                    color=ft.Colors.PRIMARY if zaznaczone else ft.Colors.ON_SURFACE,
                                ),
                                # Ta sama tablica, co na kaflu głównym — w showroomie
                                # to ona (a nie nazwa) najszybciej rozstrzyga, które
                                # z dwóch podobnych aut jest które.
                                utils.tablica_rejestracyjna(a["nr_rej"], wysokosc=20)
                                if a["nr_rej"] else ft.Text(
                                    "Brak rejestracji",
                                    size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                                    no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                            ], spacing=1, tight=True),
                        ),
                    ], spacing=0, tight=True),
                )

                karty_aut[a_id] = (ramka, odznaka)
                return ramka

            # Dokładanie auta to kolejne miejsce w showroomie, a nie pozycja
            # w menu — dlatego kafelek "Dodaj" ma wymiary karty pojazdu.
            kafel_dodaj = ft.Container(
                width=SZER_KARTY,
                border_radius=utils.RADIUS["md"],
                border=ft.Border.all(2, ft.Colors.with_opacity(0.35, ft.Colors.GREEN)),
                bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.GREEN),
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                tooltip="Dodaj nowy pojazd",
                on_click=lambda ev: dodaj(),
                content=ft.Column([
                    ft.Container(
                        width=SZER_KARTY, height=WYS_ZDJECIA, alignment=ft.Alignment.CENTER,
                        content=ft.Icon(ft.Icons.ADD_CIRCLE_OUTLINE, size=34, color=ft.Colors.GREEN),
                    ),
                    ft.Container(
                        padding=ft.Padding(8, 6, 8, 8),
                        content=ft.Text(
                            "Dodaj pojazd", size=utils.FS["body_strong"], weight="bold",
                            color=ft.Colors.GREEN, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                    ),
                ], spacing=0, tight=True),
            )

            siatka = ft.Row(
                [karta_auta(a) for a in auta_siatki] + [kafel_dodaj],
                wrap=True, spacing=10, run_spacing=10,
            )

            bs.content = ft.Container(
                padding=20,
                bgcolor=ft.Colors.SURFACE,
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.GARAGE, color=ft.Colors.PRIMARY, size=22),
                        ft.Text("Wybierz pojazd", weight="bold", size=18, color=ft.Colors.PRIMARY, expand=True),
                        ft.Text(
                            f"{len(auta_siatki)} w garażu",
                            size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.Divider(height=1),
                    siatka,
                ], tight=True, spacing=12, scroll=ft.ScrollMode.AUTO)
            )
            utils.otworz_dno(self._page, bs)

        kondycja = db.oblicz_kondycje_pojazdu(self.state.auto_id)
        kolor_kond, ikona_kond, etykieta_kond = utils.wskaznik_kondycji(kondycja)

        # Dawny bottom-sheet „Specyfikacja pojazdu” zastąpił pełny ekran /pojazd.
        # Przy komplecie danych (terminy, zakup, ubezpieczenie, ściągawka) panel
        # wysuwany rozciągał się na trzy ekrany przewijania, nie dawał się
        # przeszukać ani skopiować, a przycisk wstecz zamykał go zamiast cofać.
        def pokaz_info_auta(e):
            utils.przejdz(self._page, "/pojazd")

        # --- SZYBKA AKTUALIZACJA PRZEBIEGU (bez sztucznego tankowania/wpisu) ---
        def pokaz_szybka_aktualizacja_przebiegu(e):
            pole_przebiegu = ft.TextField(
                label="Aktualny przebieg (km)",
                value=str(aktualny_przebieg) if aktualny_przebieg else "",
                hint_text="np. 152300",
                keyboard_type=ft.KeyboardType.NUMBER,
                autofocus=True,
                **utils.styl_pola()
            )

            def zapisz(e2):
                utils.ustaw_blad(pole_przebiegu)
                nowy = utils.parsuj_int(pole_przebiegu.value, None)
                if nowy is None or nowy <= 0:
                    utils.ustaw_blad(pole_przebiegu, "Podaj poprawny przebieg")
                    self._page.update()
                    return

                if utils.sprawdz_podejrzany_przebieg(self._page, pole_przebiegu, self.state.auto_id, nowy, tabela="odczyty_przebiegu"):
                    return

                db.dodaj_odczyt_przebiegu(self.state.auto_id, nowy, zrodlo="kokpit")
                utils.zamknij_dialog(self._page, dlg)
                utils.przejdz(self._page, "/")
                utils.pokaz_komunikat(self._page, "Zaktualizowano stan licznika!")

            def zobacz_historie(e2):
                utils.zamknij_dialog(self._page, dlg)
                utils.przejdz(self._page, "/przebieg")

            dlg = ft.AlertDialog(
                modal=True,
                title=ft.Row([ft.Icon(ft.Icons.SPEED, color=ft.Colors.PRIMARY), ft.Text("Aktualizacja przebiegu", weight="bold", size=16, expand=True)], spacing=8),
                content=ft.Column([
                    ft.Text(
                        "Wpisz aktualny stan licznika z deski rozdzielczej. To tylko odświeży stan km — nie tworzy tankowania ani wpisu serwisowego.",
                        size=12, color=ft.Colors.ON_SURFACE_VARIANT
                    ),
                    pole_przebiegu,
                    ft.Container(height=5),
                    ft.TextButton("Przejdź do historii odczytów", icon=ft.Icons.SHOW_CHART, on_click=zobacz_historie)
                ], tight=True, spacing=10),
                actions=[
                    ft.TextButton("Anuluj", on_click=lambda e2: utils.zamknij_dialog(self._page, dlg)),
                    ft.ElevatedButton("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY)
                ],
                actions_alignment=ft.MainAxisAlignment.END
            )
            utils.otworz_dialog(self._page, dlg)
        # ------------------------------------------------------

        # --- KOMPAKTOWY AWATAR (60x60) Z PIERŚCIENIEM KONDYCJI ---
        WYM_AWATARA, WYM_PIERSCIENIA = 60, 68
        zdjecie_glowne = w["zdjecie_glowne"]
        if zdjecie_glowne:
            tresc_awatara = ft.Image(
                src=utils.abs_zalacznik(zdjecie_glowne), width=WYM_AWATARA, height=WYM_AWATARA,
                fit="cover", border_radius=utils.RADIUS["lg"],
            )
        else:
            tresc_awatara = ft.Container(
                width=WYM_AWATARA, height=WYM_AWATARA, border_radius=utils.RADIUS["lg"],
                bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.PRIMARY),
                alignment=ft.Alignment.CENTER,
                content=ft.Icon(ft.Icons.DIRECTIONS_CAR, size=28, color=ft.Colors.PRIMARY),
            )

        # NOWE: wartość i kolor identyczne jak w bottom-sheecie (pokaz_info_auta) —
        # tylko teraz widoczne od razu, bez klikania w "Info".
        wartosc_pierscienia = (max(0, min(100, kondycja)) / 100) if kondycja is not None else 0.0
        # Ten sam płynny kolor, co na kołowym wskaźniku w kokpicie — pierścień
        # przy awatarze i kafelek „Kondycja” nie mogą pokazywać dwóch różnych barw
        # dla tej samej liczby.
        kolor_pierscienia = utils.kolor_kondycji_plynny(kondycja)
        awatar = ft.Container(
            width=WYM_PIERSCIENIA, height=WYM_PIERSCIENIA,
            tooltip=f"Kondycja: {kondycja if kondycja is not None else '-'}/100 ({etykieta_kond})",
            on_click=pokaz_info_auta,
            content=ft.Stack([
                ft.ProgressRing(
                    value=wartosc_pierscienia, width=WYM_PIERSCIENIA, height=WYM_PIERSCIENIA,
                    stroke_width=4, color=kolor_pierscienia, stroke_cap=ft.StrokeCap.ROUND,
                    bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
                ),
                ft.Container(tresc_awatara, width=WYM_PIERSCIENIA, height=WYM_PIERSCIENIA, alignment=ft.Alignment.CENTER),
            ], width=WYM_PIERSCIENIA, height=WYM_PIERSCIENIA),
        )

        # Nagłówek szuflady prowadzi do tego samego showroomu — jedno miejsce
        # przełączania pojazdu w całej aplikacji.
        self._przelacznik_pojazdow = pokaz_wybor_aut

        tytulowy_wiersz = ft.Row([
            ft.Container(
                # expand na kontenerze I na tekście: bez tego długa nazwa
                # („OPEL ASTRA J KOMBI 1.7 CDTI”) rozpycha wiersz pod przyciski
                # po prawej, zamiast przyciąć się wielokropkiem.
                expand=True,
                content=ft.Row([
                    ft.Text(
                        str(self.state.auto_nazwa), size=16, weight="bold", color=ft.Colors.PRIMARY,
                        no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS, expand=True,
                    ),
                    ft.Icon(ft.Icons.ARROW_DROP_DOWN, color=ft.Colors.PRIMARY, size=18)
                ], spacing=0, tight=True),
                on_click=pokaz_wybor_aut,
                tooltip="Dotknij, aby wybrać z listy",
            ),
            # Chmurka pojawia się tylko przy niewysłanych zmianach tego pojazdu —
            # wcześniej trzeba było wejść w ekran Współdzielenia, żeby to zobaczyć.
            utils.wskaznik_synchronizacji(self._page, self.state.auto_id),
        ], spacing=0, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        # Rejestracja rysowana jak prawdziwa tablica. To po niej rozpoznaje się
        # auto w świecie poza aplikacją (parking, warsztat, ubezpieczyciel),
        # a jako szary tekst obok innych szarych tekstów po prostu ginęła.
        if w["nr_rej"]:
            wiersz_rejestracja = ft.Row([
                utils.tablica_rejestracyjna(
                    w["nr_rej"], wysokosc=26,
                    on_click=lambda e: utils.kopiuj_do_schowka(
                        self._page, w["nr_rej"], "Skopiowano numer rejestracyjny"),
                ),
            ], spacing=6, tight=True)
        else:
            wiersz_rejestracja = ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.BADGE, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text("Dodaj numer rejestracyjny", size=12, italic=True,
                            color=ft.Colors.ON_SURFACE_VARIANT),
                ], spacing=4),
                on_click=lambda e: utils.przejdz(self._page, f"/auto/edytuj/{self.state.auto_id}"),
                tooltip="Dotknij, aby uzupełnić dane pojazdu",
            )

        def pokaz_edycja_statusu(e):
            pole_status = ft.TextField(
                label="Status / wiadomość dla domowników",
                value=str(wiadomosc_statusu) if wiadomosc_statusu else "",
                hint_text="np. Zatankowany do pełna, Odebrałem z myjni",
                multiline=True,
                max_lines=3,
                autofocus=True,
                **utils.styl_pola()
            )

            def zapisz(e2):
                nowa_wiadomosc = (pole_status.value or "").strip()

                with db.polacz_baze() as conn:
                    conn.execute("UPDATE samochody SET wiadomosc_statusu=? WHERE id=?", (nowa_wiadomosc or None, self.state.auto_id))

                utils.zamknij_dialog(self._page, dlg)

                # Ciche wypchnięcie do chmury w tle, jeśli pojazd jest współdzielony —
                # analogicznie do zapisu tankowania (views/formularze): partner nie musi
                # ręcznie klikać "Synchronizuj", żeby zobaczyć nowy status.
                utils.wypchnij_w_tle(self._page, self.state.auto_id, "status")

                utils.przejdz(self._page, "/")
                utils.pokaz_komunikat(self._page, "Zaktualizowano status pojazdu!")

            dlg = ft.AlertDialog(
                modal=True,
                title=ft.Row([ft.Icon(ft.Icons.CHAT_BUBBLE_OUTLINE, color=ft.Colors.PRIMARY), ft.Text("Status pojazdu", weight="bold", size=16, expand=True)], spacing=8),
                content=ft.Column([
                    ft.Text("Krótka wiadomość widoczna dla wszystkich domowników korzystających z tego pojazdu.", size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                    pole_status,
                ], tight=True, spacing=10),
                actions=[
                    ft.TextButton("Anuluj", on_click=lambda e2: utils.zamknij_dialog(self._page, dlg)),
                    ft.ElevatedButton("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY),
                ],
            )
            utils.otworz_dialog(self._page, dlg)

        # Przebieg z wiekiem obok siebie: dopiero razem mówią, czy 135 tys. km
        # to dużo. Wiek jest tylko dopiskiem — dotknięcie nadal aktualizuje licznik.
        # Dopiski (wiek, przebieg roczny) sklejamy w JEDEN tekst z expand:
        # dwa osobne, sztywne teksty w tym wierszu nie miały jak się skurczyć
        # i przy dłuższych liczbach wychodziły pod przyciski po prawej stronie
        # karty — stąd wrażenie nachodzących na siebie ikon.
        dopiski = []
        if metryki_pojazdu.get("wiek_lat"):
            dopiski.append(f"{utils.formatuj_liczba(metryki_pojazdu['wiek_lat'], 1)} lat")
        if metryki_pojazdu.get("przebieg_roczny"):
            dopiski.append(f"{utils.formatuj_liczba(metryki_pojazdu['przebieg_roczny'], 0)} km/rok")

        metryki_bity = [
            ft.Icon(ft.Icons.SPEED, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Text(f"{utils.formatuj_liczba(aktualny_przebieg, 0)} km", size=13, weight="bold",
                    no_wrap=True),
            ft.Icon(ft.Icons.EDIT, size=11, color=ft.Colors.PRIMARY),
        ]
        if dopiski:
            metryki_bity.append(ft.Text(
                "•  " + "  •  ".join(dopiski),
                size=12, color=ft.Colors.ON_SURFACE_VARIANT,
                expand=True, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS))

        wiersz_przebieg = ft.Container(
            content=ft.Row(metryki_bity, spacing=5),
            on_click=pokaz_szybka_aktualizacja_przebiegu,
            on_long_press=lambda e: utils.przejdz(self._page, "/przebieg"),
            tooltip="Dotknij: aktualizuj  •  Przytrzymaj: historia licznika",
        )

        # Najbliższy termin WPROST na kaflu. Dotąd data OC czy przeglądu była
        # schowana pod przyciskiem „i” — czyli widziało ją się dopiero wtedy,
        # gdy się jej szukało, a nie wtedy, gdy zaczynała gonić.
        if najblizszy_termin:
            kolor_terminu = utils.KOLORY_STATUSU_TERMINU.get(
                najblizszy_termin["status"], ft.Colors.ON_SURFACE_VARIANT)
            wiersz_termin_kafla = ft.Container(
                padding=ft.Padding(8, 5, 8, 5),
                border_radius=utils.RADIUS["sm"],
                bgcolor=ft.Colors.with_opacity(
                    0.13 if najblizszy_termin["status"] != "ok" else 0.07, kolor_terminu),
                on_click=lambda e: utils.przejdz(self._page, "/pojazd"),
                tooltip="Wszystkie terminy pojazdu",
                content=ft.Row([
                    ft.Icon(utils.ikona_z_mapy(utils.IKONY_STATUSU_TERMINU,
                                               najblizszy_termin["status"], ft.Icons.EVENT),
                            size=13, color=kolor_terminu),
                    ft.Text(
                        f"{najblizszy_termin['etykieta']} — "
                        f"{utils.opis_dni_terminu(najblizszy_termin['dni'])}",
                        size=12, weight="bold", color=kolor_terminu, expand=True,
                        no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(najblizszy_termin["data"], size=11, color=kolor_terminu),
                ], spacing=5),
            )
        else:
            wiersz_termin_kafla = ft.Container(width=0, height=0)

        wiersz_status = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.CHAT_BUBBLE_OUTLINE, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(
                    str(wiadomosc_statusu) if wiadomosc_statusu else "Dodaj status dla domowników...",
                    size=13,
                    italic=not bool(wiadomosc_statusu),
                    color=ft.Colors.ON_SURFACE if wiadomosc_statusu else ft.Colors.ON_SURFACE_VARIANT,
                    no_wrap=True,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    expand=True,
                ),
            ], spacing=5),
            on_click=pokaz_edycja_statusu,
            tooltip="Dotknij, aby ustawić status dla domowników",
        )

        kolumna_tekstowa = ft.Column([
            tytulowy_wiersz,
            wiersz_rejestracja,
            wiersz_przebieg,
            wiersz_status,
        ], spacing=4, expand=True)

        # JEDEN przycisk zamiast dwóch. Ołówek „Edytuj pojazd” stał tuż pod
        # ikoną „i”, a nad nimi w tym samym wierszu siedział jeszcze ołówek
        # aktualizacji przebiegu — trzy podobne ikony na przestrzeni 60 px, przy
        # czym dwie z nich robiły co innego. Edycja danych pojazdu jest o jedno
        # dotknięcie dalej: z Karty pojazdu i z szuflady („Edytuj dane pojazdu”),
        # a to nie jest czynność, którą robi się codziennie.
        przyciski_karty = ft.IconButton(
            icon=ft.Icons.INFO_OUTLINE, icon_size=20, icon_color=ft.Colors.PRIMARY,
            tooltip="Karta pojazdu: terminy, wartość, ubezpieczenie, ściągawka",
            on_click=pokaz_info_auta,
            style=ft.ButtonStyle(padding=0), width=36, height=36,
        )

        # --- TŁO KARTY: rozmyte zdjęcie pojazdu zamiast płaskiego koloru ---
        # Zdjęcie idzie pod treść mocno rozmyte i przykryte gradientem w kolorze
        # powierzchni. Karta ma nieść „to jest MOJE auto" barwą i kształtem
        # widocznym kątem oka, a nie czytelnym obrazkiem — pod nazwą, rejestracją
        # i statusem musi zostać tło o przewidywalnym kontraście, niezależnie od
        # tego, czy zdjęcie jest jasne, ciemne czy kontrastowe.
        PROMIEN_KARTY = 12  # zgodny z domyślnym kształtem ft.Card (RoundedRectangleBorder 12)

        tresc_karty = ft.Container(
            padding=12, border_radius=PROMIEN_KARTY,
            content=ft.Column([
                ft.Row([awatar, kolumna_tekstowa, przyciski_karty], spacing=12,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                wiersz_termin_kafla,
            ], spacing=8),
        )

        if zdjecie_glowne:
            wnetrze_karty = ft.Stack([
                # Warstwa 1 — zdjęcie wypełniające całą kartę (kadrowane, nie skalowane).
                ft.Container(
                    left=0, top=0, right=0, bottom=0,
                    border_radius=PROMIEN_KARTY,
                    image=ft.DecorationImage(
                        src=utils.abs_zalacznik(zdjecie_glowne),
                        fit=ft.BoxFit.COVER,
                        alignment=ft.Alignment.CENTER,
                    ),
                ),
                # Warstwa 2 — rozmycie tego, co pod spodem, plus gradient w kolorze
                # motywu. Gradient jest lżejszy w lewym górnym rogu (przy awatarze),
                # a gęstnieje w stronę wiersza statusu, czyli tam, gdzie tekstu
                # jest najwięcej.
                ft.Container(
                    left=0, top=0, right=0, bottom=0,
                    border_radius=PROMIEN_KARTY,
                    blur=ft.Blur(18, 18),
                    gradient=ft.LinearGradient(
                        begin=ft.Alignment.TOP_LEFT,
                        end=ft.Alignment.BOTTOM_RIGHT,
                        colors=[
                            ft.Colors.with_opacity(0.74, ft.Colors.SURFACE),
                            ft.Colors.with_opacity(0.93, ft.Colors.SURFACE),
                        ],
                    ),
                ),
                tresc_karty,
            ])
        else:
            wnetrze_karty = tresc_karty

        karta_auta = ft.Card(
            elevation=1,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            content=wnetrze_karty,
        )

        wiele_aut = len(auta) > 1 and not czy_sprzedany

        if czy_sprzedany:
            # Bez tego paska podgląd archiwalnego auta wyglądałby dokładnie jak
            # zwykły garaż — z FAB-em zachęcającym do dopisania tankowania do
            # samochodu, którego się już nie ma.
            data_sprzedazy = dane_pojazdu.get("data_sprzedazy")
            self.elementy.append(ft.Container(
                padding=ft.Padding(12, 8, 8, 8), border_radius=utils.RADIUS["lg"],
                bgcolor=ft.Colors.with_opacity(0.14, ft.Colors.BLUE_GREY_500),
                content=ft.Row([
                    ft.Icon(ft.Icons.INVENTORY, size=18, color=ft.Colors.BLUE_GREY_700),
                    ft.Text(
                        "Pojazd sprzedany" + (f" {data_sprzedazy}" if data_sprzedazy else "")
                        + " — podgląd archiwalny.",
                        size=12, weight="bold", color=ft.Colors.BLUE_GREY_700, expand=True,
                    ),
                    ft.TextButton("Archiwum", icon=ft.Icons.ARROW_FORWARD,
                                  on_click=lambda e: utils.przejdz(self._page, "/archiwum")),
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ))

        wiersz_karty_z_nawigacja = ft.Row([
            ft.IconButton(
                icon=ft.Icons.CHEVRON_LEFT, icon_size=26, icon_color=ft.Colors.PRIMARY,
                tooltip="Poprzedni pojazd", on_click=on_prev, visible=wiele_aut,
                style=ft.ButtonStyle(padding=0),
            ),
            ft.Container(karta_auta, expand=True),
            ft.IconButton(
                icon=ft.Icons.CHEVRON_RIGHT, icon_size=26, icon_color=ft.Colors.PRIMARY,
                tooltip="Następny pojazd", on_click=on_next, visible=wiele_aut,
                style=ft.ButtonStyle(padding=0),
            ),
        ], spacing=2, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        self.elementy.append(wiersz_karty_z_nawigacja)
