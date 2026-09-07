import flet as ft
import asyncio
import db
import sync
import utils


# Kolejność ma znaczenie: od najszerszych uprawnień do najwęższych, żeby
# rozdający kod czytał listę jak zjazd w dół, a nie losowy zbiór opcji.
OPIS_KODOW = [
    ("pelny", db.ROLA_PELNA, ft.Icons.KEY,
     "Robi wszystko to, co Ty: dodaje, poprawia i kasuje dowolny wpis. Dla drugiego właściciela auta."),
    ("wspolautor", db.ROLA_WSPOLAUTOR, ft.Icons.EDIT_NOTE,
     "Dopisuje własne tankowania i wpisy, poprawia to, co sam dodał. Cudzych nie ruszy. Dla kogoś, kto jeździ autem na co dzień."),
    ("podglad", db.ROLA_PODGLAD, ft.Icons.VISIBILITY,
     "Widzi całą historię, nie zmienia niczego. Nic z jego telefonu nie trafia do chmury. Dla kupującego, warsztatu, rodzica."),
]


class WspoldzielenieView(ft.View):
    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state

        appbar = utils.zbuduj_pasek_z_powrotem(page, "Współdzielenie pojazdu", "/", ikona=ft.Icons.GROUPS)

        wspolny_id, kod = (None, None)
        if self.state.auto_id:
            wspolny_id, kod = sync.czy_udostepniony(self.state.auto_id)

        self.rola = db.rola_pojazdu(self.state.auto_id) if self.state.auto_id else db.ROLA_WLASCICIEL
        self.jestem_gospodarzem = self.rola in db.ROLE_Z_PELNYM_DOSTEPEM

        elementy = []

        if wspolny_id:
            elementy.append(self._karta_statusu(kod))
            if self.jestem_gospodarzem:
                elementy.append(self._karta_zaproszen())
            elementy.append(self._karta_synchronizacji())
            elementy.append(self._karta_rozlaczenia())

        elif self.state.auto_id:
            elementy.append(utils.karta_formularza([
                ft.Text(
                    f"Udostępnij „{self.state.auto_nazwa}”, aby partner, rodzina albo mechanik "
                    f"widzieli historię tego auta na własnym telefonie — bez zakładania kont, tylko kodem.",
                    size=13, color=ft.Colors.ON_SURFACE_VARIANT
                ),
                ft.Container(height=4),
                ft.Text("Po udostępnieniu dostaniesz trzy różne kody:", size=12, weight="bold"),
            ] + [self._wiersz_opisu_roli(rola, ikona, opis) for _, rola, ikona, opis in OPIS_KODOW] + [
                ft.Container(height=6),
                ft.ElevatedButton("Udostępnij ten pojazd", on_click=self._udostepnij,
                                  bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY)
            ], "Udostępnij", ft.Icons.SHARE, domyslnie_otwarte=True))

        self.e_kod = ft.TextField(label="Kod zaproszenia", hint_text="np. A1B2C3", **utils.styl_pola())
        elementy.append(utils.karta_formularza([
            ft.Text(
                "Masz kod od kogoś innego? Wpisz go tutaj — na liście pojawi się nowy pojazd ze wspólną "
                "historią. To, co będziesz mógł w nim zrobić, zależy od tego, który kod dostałeś.",
                size=12, color=ft.Colors.ON_SURFACE_VARIANT
            ),
            self.e_kod,
            ft.ElevatedButton("Dołącz po kodzie", on_click=self._dolacz,
                              bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY)
        ], "Dołącz do cudzego pojazdu", ft.Icons.LOGIN))

        elementy.append(utils.dol_bezpieczny(20))

        super().__init__(
            route="/wspoldzielenie", padding=15, spacing=15,
            scroll=ft.ScrollMode.AUTO, appbar=appbar, controls=elementy
        )

    # ------------------------------------------------------------ KARTY
    def _wiersz_opisu_roli(self, rola, ikona, opis):
        kolor = utils.KOLORY_ROL.get(rola, ft.Colors.PRIMARY)
        return ft.Row([
            ft.Icon(ikona, size=17, color=kolor),
            ft.Column([
                ft.Text(db.ETYKIETY_ROL.get(rola, rola), size=12, weight="bold", color=kolor),
                ft.Text(opis, size=11, color=ft.Colors.ON_SURFACE_VARIANT),
            ], spacing=0, tight=True, expand=True),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START)

    def _karta_statusu(self, kod):
        """Co ten pojazd znaczy dla MNIE. U gospodarza — że jest rozdawany;
        u gościa — z jakimi prawami go widzi."""
        kolor = utils.KOLORY_ROL.get(self.rola, ft.Colors.PRIMARY)
        tresc = [
            ft.Row([
                ft.Icon(utils.IKONY_ROL.get(self.rola, ft.Icons.CHECK_CIRCLE), color=kolor),
                ft.Text(
                    "Ten pojazd jest współdzielony" if self.jestem_gospodarzem
                    else f"Dołączyłeś do tego pojazdu — {db.ETYKIETY_ROL.get(self.rola, self.rola).lower()}",
                    weight="bold", expand=True
                ),
            ]),
            ft.Text(db.OPISY_ROL.get(self.rola, ""), size=13, color=ft.Colors.ON_SURFACE_VARIANT),
        ]

        if not self.jestem_gospodarzem:
            tresc.append(ft.Text(
                "Kody zaproszeń wystawia wyłącznie właściciel pojazdu — dlatego nie widzisz ich u siebie.",
                size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
            ))

        tresc.append(ft.Text(
            "Synchronizują się wszystkie dane pojazdu (dane pojazdu, tankowania, serwis, wizyty, magazyn, "
            "opony, koszty, warsztaty, wydatki cykliczne, odczyty przebiegu, trasy, checklisty, budżety, "
            "tagi i lista Do zrobienia) — poza zdjęciami (profilowym, karoserii i załącznikami), które "
            "zawsze zostają lokalnie na każdym urządzeniu.",
            size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
        ))
        tresc.append(ft.OutlinedButton("Zobacz podział kosztów", icon=ft.Icons.PIE_CHART,
                                       on_click=lambda e: utils.przejdz(self._page, "/podzial")))
        tresc.append(ft.Text(
            "Wskazówka: ustaw swoje imię w Ustawieniach, aby nowe wpisy były podpisywane Twoim imieniem — "
            "bez podpisu współautor nie odróżni swoich wpisów od cudzych.",
            size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
        ))

        return utils.karta_formularza(tresc, "Status współdzielenia", ft.Icons.PEOPLE, domyslnie_otwarte=True)

    def _karta_zaproszen(self):
        """Trzy kody, każdy z jednym zdaniem o tym, co daje. Wcześniej kod był
        jeden i dawał wszystko — także prawo skasowania cudzego tankowania
        sprzed roku."""
        kody = db.kody_dostepu(self.state.auto_id)
        elementy = [ft.Text(
            "Każdy kod otwiera ten sam pojazd, ale z innymi prawami. Rozdawaj ten, który pasuje do osoby.",
            size=13, color=ft.Colors.ON_SURFACE_VARIANT
        )]

        for klucz, rola, ikona, opis in OPIS_KODOW:
            elementy.append(self._wiersz_kodu(kody.get(klucz), rola, ikona, opis))

        brakuje = not kody.get("wspolautor") or not kody.get("podglad")
        if brakuje:
            elementy.append(ft.Container(
                padding=ft.Padding(10, 8, 10, 8),
                border_radius=utils.RADIUS["sm"],
                bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.ORANGE_700),
                content=ft.Text(
                    "Kody ograniczonego dostępu nie są jeszcze założone. Wymagają jednorazowego wgrania "
                    "pliku supabase/role_wspoldzielenia.sql w edytorze SQL Twojego projektu Supabase — "
                    "bez tego serwer nie wie, co znaczy „tylko podgląd”.",
                    size=11, color=ft.Colors.ORANGE_800
                ),
            ))
            elementy.append(ft.ElevatedButton("Utwórz kody ról", icon=ft.Icons.ADD_MODERATOR,
                                              on_click=self._utworz_kody))
        else:
            elementy.append(ft.OutlinedButton("Wygeneruj nowe kody ról", icon=ft.Icons.AUTORENEW,
                                              on_click=self._odswiez_kody))
            elementy.append(ft.Text(
                "Nowe kody unieważniają stare. Osoby, które już dołączyły, zostają — kod służy do wejścia, "
                "nie do trzymania dostępu.",
                size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
            ))

        return utils.karta_formularza(elementy, "Kogo zapraszasz", ft.Icons.QR_CODE_2, domyslnie_otwarte=True)

    def _wiersz_kodu(self, kod, rola, ikona, opis):
        kolor = utils.KOLORY_ROL.get(rola, ft.Colors.PRIMARY)

        def _kopiuj(e, k=kod):
            # Przez utils, bo page.set_clipboard istnieje tylko w starszych
            # wersjach Fleta — wcześniej wyjątek był łykany, a komunikat
            # „Skopiowano kod!” pokazywał się mimo pustego schowka.
            utils.kopiuj_do_schowka(self._page, k or "", "Skopiowano kod!")

        naglowek = ft.Row([
            ft.Icon(ikona, size=17, color=kolor),
            ft.Text(db.ETYKIETY_ROL.get(rola, rola), size=13, weight="bold", color=kolor, expand=True),
        ], spacing=8)

        if kod:
            pasek = ft.Row([
                ft.Text(kod, size=20, weight="bold", color=kolor, selectable=True, expand=True),
                ft.IconButton(ft.Icons.COPY, tooltip="Kopiuj kod", icon_color=kolor, on_click=_kopiuj),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
        else:
            pasek = ft.Text("— jeszcze nie założony —", size=13, italic=True,
                            color=ft.Colors.ON_SURFACE_VARIANT)

        return ft.Container(
            padding=ft.Padding(12, 10, 12, 10),
            border_radius=utils.RADIUS["sm"],
            bgcolor=ft.Colors.with_opacity(0.07, kolor),
            content=ft.Column([
                naglowek,
                ft.Text(opis, size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                pasek,
            ], spacing=4, tight=True),
        )

    def _karta_synchronizacji(self):
        """Pełny stan synchronizacji mieszka tutaj, a nie pod przyciskiem
        w nagłówkach zakładek — tam rozpychał wiersz, w którym obok stoją inne
        akcje, i został skrócony do samego czasu z kropką."""
        zalegle = db.opis_oczekujacej_synchronizacji()
        tylko_czytam = (self.rola == db.ROLA_PODGLAD)

        elementy = [
            ft.Row([
                ft.Icon(ft.Icons.SCHEDULE, size=16, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(utils.tekst_ostatniej_synchronizacji(krotki=False).split(" • ")[0],
                        size=12, color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        ]

        if zalegle and not tylko_czytam:
            elementy.append(ft.Container(
                padding=ft.Padding(10, 8, 10, 8),
                border_radius=utils.RADIUS["sm"],
                bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.ORANGE_700),
                content=ft.Row([
                    ft.Icon(ft.Icons.CLOUD_UPLOAD, size=16, color=ft.Colors.ORANGE_800),
                    ft.Text(f"{zalegle} — wyślą się przy najbliższej udanej synchronizacji.",
                            size=12, color=ft.Colors.ORANGE_800, expand=True),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ))

        elementy.append(ft.Text(
            "Pobierz najnowszą historię pojazdu." if tylko_czytam
            else "Kliknij, aby wysłać swoje nowe i zmienione dane oraz pobrać te od pozostałych.",
            size=13, color=ft.Colors.ON_SURFACE_VARIANT
        ))
        elementy.append(ft.ElevatedButton(
            "Pobierz zmiany" if tylko_czytam else "Synchronizuj teraz",
            icon=ft.Icons.SYNC, on_click=self._synchronizuj,
            bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY
        ))

        # --- automatyczna synchronizacja ---
        elementy += [
            ft.Container(height=6),
            ft.Divider(height=1),
            ft.Switch(
                label="Sprawdzaj zmiany automatycznie",
                value=db.czy_auto_synchronizacja(),
                on_change=self._przelacz_auto,
            ),
            ft.Text(
                "Aplikacja sama dociąga cudze zmiany przy starcie, przy powrocie z tła i co jakiś czas, "
                "gdy jest otwarta. Bez tego zobaczysz je dopiero, gdy sam coś zapiszesz.",
                size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
            ),
        ]
        if db.czy_auto_synchronizacja():
            biezacy = db.interwal_auto_synchronizacji()
            opcje = [("co 5 min", 5, None), ("co 15 min", 15, None), ("co godzinę", 60, None)]
            wybrany = min((o[1] for o in opcje), key=lambda m: abs(m - biezacy))
            elementy.append(utils.segmented_control(self._page, opcje, wybrany, self._ustaw_interwal))

        # --- ratunki ---
        elementy += [
            ft.Container(height=6),
            ft.Divider(height=1),
            ft.Text(
                "Przypadkowo coś skasowałeś i jeszcze NIE kliknąłeś „Synchronizuj teraz”? "
                "To przywróci to z chmury, zanim usunięcie zdąży się wysłać. Jeśli usunięcie "
                "już zostało zsynchronizowane, tędy się go nie cofnie — trzeba dodać wpis ponownie ręcznie.",
                size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
            ),
            ft.OutlinedButton("Przywróć z chmury", icon=ft.Icons.CLOUD_DOWNLOAD, on_click=self._przywroc),
            ft.Text(
                "Zwykła synchronizacja pobiera tylko to, co zmieniło się od ostatniego razu. Jeśli coś się "
                "rozjechało (np. po wgraniu kopii bazy), każ jej przejść całą chmurę od nowa.",
                size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
            ),
            ft.OutlinedButton("Pobierz wszystko od nowa", icon=ft.Icons.REFRESH, on_click=self._pelna_sync),
        ]

        return utils.karta_formularza(elementy, "Synchronizacja", ft.Icons.SYNC)

    def _karta_rozlaczenia(self):
        if self.jestem_gospodarzem:
            return utils.karta_formularza([
                ft.Text(
                    "Odłącz ten pojazd od chmury. Wróci do trybu w pełni offline, a wszystkie kody "
                    "przestaną działać. Dotychczasowe dane pozostaną bezpieczne na Twoim telefonie, "
                    "ale przestaną się synchronizować z innymi.",
                    size=13, color=ft.Colors.ON_SURFACE_VARIANT
                ),
                ft.ElevatedButton("Rozłącz pojazd", on_click=self._odlacz,
                                  bgcolor=ft.Colors.RED_700, color=ft.Colors.WHITE)
            ], "Niebezpieczna strefa", ft.Icons.WARNING_AMBER_ROUNDED)

        return utils.karta_formularza([
            ft.Text(
                "Przestań obserwować ten pojazd. Zniknie z Twojej listy aktualizacji, a to, co masz "
                "pobrane, zostanie na telefonie jako zwykły, offline'owy pojazd. Właściciela to nie dotknie.",
                size=13, color=ft.Colors.ON_SURFACE_VARIANT
            ),
            ft.ElevatedButton("Przestań obserwować", on_click=self._odlacz,
                              bgcolor=ft.Colors.RED_700, color=ft.Colors.WHITE)
        ], "Niebezpieczna strefa", ft.Icons.WARNING_AMBER_ROUNDED)

    # ------------------------------------------------------------ AKCJE
    def _przelacz_auto(self, e):
        db.zapisz_auto_synchronizacje(bool(e.control.value))
        utils.przejdz(self._page, "/wspoldzielenie")

    def _ustaw_interwal(self, minuty):
        db.zapisz_interwal_auto_synchronizacji(int(minuty))
        utils.pokaz_komunikat(self._page, f"Sprawdzanie zmian co {int(minuty)} min.")

    def _utworz_kody(self, e):
        self._zroba_kody(sync.utworz_kody_rol, "Kody ról są gotowe.")

    def _odswiez_kody(self, e):
        def wykonaj():
            self._zroba_kody(sync.uniewaznij_kody_rol, "Wystawiono nowe kody. Stare przestały działać.")

        utils.potwierdz(
            self._page,
            "Wygenerować nowe kody?",
            "Dotychczasowy kod współautora i kod podglądu przestaną działać. Osoby, które już dołączyły, "
            "zachowają dostęp — kod służy do wejścia, nie do jego utrzymania.",
            wykonaj,
            tekst_potwierdzenia="Wygeneruj"
        )

    def _zroba_kody(self, funkcja, komunikat):
        async def _zrob():
            dlg = utils.pokaz_ladowanie(self._page, "Przygotowywanie kodów...")
            try:
                await asyncio.to_thread(funkcja, self.state.auto_id)
                utils.ukryj_ladowanie(self._page, dlg)
                utils.przejdz(self._page, "/wspoldzielenie")
                utils.pokaz_komunikat(self._page, komunikat)
            except Exception as ex:
                utils.ukryj_ladowanie(self._page, dlg)
                utils.pokaz_komunikat(
                    self._page,
                    f"Nie udało się założyć kodów ról: {ex}. Najczęstsza przyczyna to niewgrany plik "
                    f"supabase/role_wspoldzielenia.sql — kod pełnego dostępu działa niezależnie.",
                    ft.Colors.RED_700
                )
        self._page.run_task(_zrob)

    def _odlacz(self, e):
        gospodarz = self.jestem_gospodarzem

        def wykonaj():
            sync.odlacz_wspoldzielenie(self.state.auto_id)
            utils.przejdz(self._page, "/wspoldzielenie")
            utils.pokaz_komunikat(
                self._page,
                "Pomyślnie odłączono pojazd z chmury." if gospodarz
                else "Pojazd przestał się aktualizować. Pobrane dane zostały na telefonie."
            )

        utils.potwierdz(
            self._page,
            "Zakończyć współdzielenie?" if gospodarz else "Przestać obserwować pojazd?",
            "Twój pojazd zostanie odłączony od chmury. Zapisane dane pozostaną na telefonie, ale przestaną "
            "się aktualizować u innych." if gospodarz else
            "Pojazd zostanie u Ciebie jako zwykłe, offline'owe auto z tym, co zdążyłeś pobrać. "
            "Żeby wrócić, będziesz potrzebował kodu od właściciela.",
            wykonaj,
            tekst_potwierdzenia="Rozłącz" if gospodarz else "Przestań obserwować"
        )

    def _udostepnij(self, e):
        async def _zrob():
            dlg = utils.pokaz_ladowanie(self._page, "Tworzenie udostępnionego pojazdu...")
            try:
                kod = await asyncio.to_thread(sync.utworz_udostepniony_pojazd, self.state.auto_id, self.state.auto_nazwa)
                utils.ukryj_ladowanie(self._page, dlg)
                utils.przejdz(self._page, "/wspoldzielenie")
                utils.pokaz_komunikat(self._page, f"Udostępniono! Kod pełnego dostępu: {kod}")
            except Exception as ex:
                utils.ukryj_ladowanie(self._page, dlg)
                utils.pokaz_komunikat(self._page, f"Błąd łączenia z Supabase: {ex}", ft.Colors.RED_700)
        self._page.run_task(_zrob)

    def _dolacz(self, e):
        kod = (self.e_kod.value or "").strip()
        if not kod:
            utils.ustaw_blad(self.e_kod, "Podaj kod")
            self._page.update()
            return

        async def _zrob():
            dlg = utils.pokaz_ladowanie(self._page, "Dołączanie do pojazdu...")
            try:
                nowy_auto_id, nazwa, kolizja_nazwy, rola = await asyncio.to_thread(sync.dolacz_po_kodzie, kod)
                utils.ukryj_ladowanie(self._page, dlg)
                self.state.auto_id = nowy_auto_id
                self.state.auto_nazwa = nazwa
                utils.przejdz(self._page, "/")
                etykieta = db.ETYKIETY_ROL.get(rola, rola).lower()
                if kolizja_nazwy:
                    utils.pokaz_komunikat(
                        self._page,
                        f"Dołączono jako nowy, osobny pojazd „{nazwa}” ({etykieta}). Miałeś/aś już auto o tej samej "
                        f"nazwie, więc dopisaliśmy odróżnik, żeby ich nie pomylić — to dwa niezależne pojazdy.",
                        ft.Colors.ORANGE_700
                    )
                elif rola == db.ROLA_PODGLAD:
                    utils.pokaz_komunikat(
                        self._page,
                        f"Dołączono do pojazdu „{nazwa}” w trybie tylko do odczytu — widzisz historię, ale jej nie zmieniasz."
                    )
                elif rola == db.ROLA_WSPOLAUTOR:
                    utils.pokaz_komunikat(
                        self._page,
                        f"Dołączono do pojazdu „{nazwa}” jako współautor — dopisujesz własne wpisy, cudzych nie zmieniasz."
                    )
                else:
                    utils.pokaz_komunikat(self._page, f"Dołączono do pojazdu „{nazwa}”! Zaimportowano dotychczasową historię.")
            except Exception as ex:
                utils.ukryj_ladowanie(self._page, dlg)
                utils.pokaz_komunikat(self._page, f"Błąd: {ex}", ft.Colors.RED_700)
        self._page.run_task(_zrob)

    def _synchronizuj(self, e):
        self._uruchom_synchronizacje(lambda: sync.synchronizuj_wszystko(self.state.auto_id))

    def _pelna_sync(self, e):
        def wykonaj():
            self._uruchom_synchronizacje(
                lambda: sync.pelna_synchronizacja(self.state.auto_id),
                komunikat="Przechodzenie całej chmury od nowa..."
            )

        utils.potwierdz(
            self._page,
            "Pobrać wszystko od nowa?",
            "Aplikacja przejdzie komplet rekordów z chmury zamiast samych zmian. Potrwa dłużej i zużyje "
            "więcej transferu, ale wyrówna wszystko, co mogło się rozjechać.",
            wykonaj,
            tekst_potwierdzenia="Pobierz"
        )

    def _uruchom_synchronizacje(self, funkcja, komunikat="Synchronizowanie danych..."):
        async def _zrob():
            dlg = utils.pokaz_ladowanie(self._page, komunikat)
            try:
                wyslano, pobrano = await asyncio.to_thread(funkcja)
                await asyncio.to_thread(sync.przetworz_kolejke_sync)
                utils.ukryj_ladowanie(self._page, dlg)
                utils.przejdz(self._page, "/wspoldzielenie")

                konflikty = sync.pobierz_konflikty_ostatniej_synchronizacji()
                odrzucone = sync.pobierz_odrzucone_ostatniej_synchronizacji()
                if konflikty:
                    utils.pokaz_komunikat(self._page, utils.podsumowanie_konfliktow(konflikty), ft.Colors.AMBER_700)
                    utils.pokaz_dialog_konfliktow(self._page, konflikty, self.state.auto_id)
                elif odrzucone:
                    utils.pokaz_komunikat(self._page, utils.podsumowanie_odrzuconych(odrzucone), ft.Colors.ORANGE_700)
                elif self.rola == db.ROLA_PODGLAD:
                    utils.pokaz_komunikat(self._page, f"Pobrano {pobrano} zmian.")
                else:
                    utils.pokaz_komunikat(self._page, f"Wysłano {wyslano}, pobrano {pobrano} nowych rekordów.")
            except sync.SynchronizacjaWToku:
                utils.ukryj_ladowanie(self._page, dlg)
                utils.pokaz_komunikat(self._page, "Synchronizacja już trwa — chwilę to potrwa.")
            except Exception as ex:
                db.zakolejkuj_synchronizacje(self.state.auto_id, "reczna", str(ex))
                utils.ukryj_ladowanie(self._page, dlg)
                utils.pokaz_komunikat(
                    self._page,
                    f"Błąd synchronizacji: {ex}. Zmiany zostały zakolejkowane i spróbujemy ponownie automatycznie.",
                    ft.Colors.RED_700
                )
        self._page.run_task(_zrob)

    def _przywroc(self, e):
        def wykonaj():
            async def _zrob():
                dlg = utils.pokaz_ladowanie(self._page, "Przywracanie danych z chmury...")
                try:
                    przywrocono = await asyncio.to_thread(sync.przywroc_z_chmury, self.state.auto_id)
                    utils.ukryj_ladowanie(self._page, dlg)
                    utils.przejdz(self._page, "/wspoldzielenie")
                    if przywrocono:
                        utils.pokaz_komunikat(self._page, f"Przywrócono {przywrocono} rekordów z chmury.")
                    else:
                        utils.pokaz_komunikat(self._page, "Brak danych do przywrócenia — wszystko już jest na miejscu.")
                except Exception as ex:
                    utils.ukryj_ladowanie(self._page, dlg)
                    utils.pokaz_komunikat(self._page, f"Błąd przywracania: {ex}", ft.Colors.RED_700)
            self._page.run_task(_zrob)

        utils.potwierdz(
            self._page,
            "Przywrócić dane z chmury?",
            "Pobierze wszystko, co jest jeszcze żywe na serwerze, a czego brakuje lokalnie. Nie cofnie usunięć, które zdążyły się już zsynchronizować.",
            wykonaj,
            tekst_potwierdzenia="Przywróć"
        )
