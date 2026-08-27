import flet as ft
import asyncio
import sync
import utils


class WspoldzielenieView(ft.View):
    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state

        appbar = utils.zbuduj_pasek_z_powrotem(page, "🤝 Współdzielenie pojazdu", "/")

        wspolny_id, kod = (None, None)
        if self.state.auto_id:
            wspolny_id, kod = sync.czy_udostepniony(self.state.auto_id)

        elementy = []

        if wspolny_id:
            def _kopiuj(e, k=kod):
                try:
                    self._page.set_clipboard(k or "")
                except Exception:
                    pass
                utils.pokaz_komunikat(self._page, "Skopiowano kod!")

            # 1. Status współdzielenia
            elementy.append(utils.karta_formularza([
                ft.Row([ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN_700), ft.Text("Ten pojazd jest współdzielony", weight="bold")]),
                ft.Text("Podaj ten kod partnerowi/rodzinie — po wpisaniu go w ich aplikacji zobaczą ten pojazd i dopiszą tankowania.", size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Container(
                    padding=15, border_radius=10, bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.PRIMARY),
                    content=ft.Row([
                        ft.Text(kod or "-", size=22, weight="bold", color=ft.Colors.PRIMARY, selectable=True),
                        ft.IconButton(ft.Icons.COPY, tooltip="Kopiuj kod", on_click=_kopiuj)
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                ),
                    ft.Text("Synchronizują się teraz wszystkie dane pojazdu (dane pojazdu, tankowania, serwis, wizyty, magazyn, opony, koszty, warsztaty, wydatki cykliczne, odczyty przebiegu, tagi i lista Do zrobienia) — poza zdjęciami (profilowym, karoserii i załącznikami), które zawsze zostają lokalnie na każdym urządzeniu.", size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT),
            ], "Status współdzielenia", ft.Icons.PEOPLE, domyslnie_otwarte=True))

            # 2. Ręczna synchronizacja
            elementy.append(utils.karta_formularza([
                ft.Text("Kliknij, aby wysłać swoje nowe/zmienione dane i pobrać te od partnera.", size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.ElevatedButton("🔄 Synchronizuj teraz", on_click=self._synchronizuj, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY),
                ft.Container(height=10),
                ft.Divider(height=1),
                ft.Container(height=10),
                ft.Text(
                    "Przypadkowo coś skasowałeś i jeszcze NIE kliknąłeś „Synchronizuj teraz”? "
                    "To przywróci to z chmury, zanim usunięcie zdąży się wysłać. Jeśli usunięcie "
                    "już zostało zsynchronizowane, tędy się go nie cofnie — trzeba dodać wpis ponownie ręcznie.",
                    size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
                ),
                ft.OutlinedButton("♻️ Przywróć z chmury", on_click=self._przywroc)
            ], "Synchronizacja", ft.Icons.SYNC))

            # --- NOWE: 3. Zakończenie współdzielenia ---
            elementy.append(utils.karta_formularza([
                ft.Text("Odłącz ten pojazd od chmury. Wróci on do trybu w pełni offline. Wszystkie dotychczasowe tankowania pozostaną bezpieczne na Twoim telefonie, ale przestaną się synchronizować z innymi.", size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.ElevatedButton("Rozłącz pojazd", on_click=self._odlacz, bgcolor=ft.Colors.RED_700, color=ft.Colors.WHITE)
            ], "Niebezpieczna strefa", ft.Icons.WARNING_AMBER_ROUNDED))

        elif self.state.auto_id:
            elementy.append(utils.karta_formularza([
                ft.Text(f"Udostępnij „{self.state.auto_nazwa}”, aby partner/rodzina mogli dopisywać tankowania z własnego telefonu — bez zakładania kont, tylko kodem.", size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.ElevatedButton("Udostępnij ten pojazd", on_click=self._udostepnij, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY)
            ], "Udostępnij", ft.Icons.SHARE, domyslnie_otwarte=True))

        self.e_kod = ft.TextField(label="Kod zaproszenia od partnera", hint_text="np. A1B2C3", **utils.styl_pola())
        elementy.append(utils.karta_formularza([
            ft.Text("Masz kod od kogoś innego? Wpisz go tutaj — na liście pojawi się nowy pojazd ze wspólną historią tankowań.", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            self.e_kod,
            ft.ElevatedButton("Dołącz po kodzie", on_click=self._dolacz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY)
        ], "Dołącz do cudzego pojazdu", ft.Icons.LOGIN))

        elementy.append(utils.dol_bezpieczny(20))

        super().__init__(
            route="/wspoldzielenie", padding=15, spacing=15,
            scroll=ft.ScrollMode.AUTO, appbar=appbar, controls=elementy
        )

    # --- NOWA FUNKCJA DO OBSŁUGI PRZYCISKU ---
    def _odlacz(self, e):
        def wykonaj():
            sync.odlacz_wspoldzielenie(self.state.auto_id)
            utils.przejdz(self._page, "/wspoldzielenie")
            utils.pokaz_komunikat(self._page, "Pomyślnie odłączono pojazd z chmury.")
            
        utils.potwierdz(
            self._page, 
            "Zakończyć współdzielenie?", 
            "Twój pojazd zostanie odłączony od chmury. Zapisane dane pozostaną na telefonie, ale przestaną się aktualizować u innych.", 
            wykonaj,
            tekst_potwierdzenia="Rozłącz"
        )

    def _udostepnij(self, e):
        async def _zrob():
            try:
                kod = await asyncio.to_thread(sync.utworz_udostepniony_pojazd, self.state.auto_id, self.state.auto_nazwa)
                utils.przejdz(self._page, "/wspoldzielenie")
                utils.pokaz_komunikat(self._page, f"Udostępniono! Kod zaproszenia: {kod}")
            except Exception as ex:
                utils.pokaz_komunikat(self._page, f"Błąd łączenia z Supabase: {ex}", ft.Colors.RED_700)
        self._page.run_task(_zrob)

    def _dolacz(self, e):
        kod = (self.e_kod.value or "").strip()
        if not kod:
            self.e_kod.error_text = "Podaj kod"
            self._page.update()
            return

        async def _zrob():
            try:
                nowy_auto_id, nazwa = await asyncio.to_thread(sync.dolacz_po_kodzie, kod)
                self.state.auto_id = nowy_auto_id
                self.state.auto_nazwa = nazwa
                utils.przejdz(self._page, "/")
                utils.pokaz_komunikat(self._page, f"Dołączono do pojazdu „{nazwa}”! Zaimportowano dotychczasowe tankowania.")
            except Exception as ex:
                utils.pokaz_komunikat(self._page, f"Błąd: {ex}", ft.Colors.RED_700)
        self._page.run_task(_zrob)

    def _synchronizuj(self, e):
        async def _zrob():
            try:
                wyslano, pobrano = await asyncio.to_thread(sync.synchronizuj_wszystko, self.state.auto_id)
                utils.przejdz(self._page, "/wspoldzielenie")
                utils.pokaz_komunikat(self._page, f"Wysłano {wyslano}, pobrano {pobrano} nowych rekordów.")
            except Exception as ex:
                utils.pokaz_komunikat(self._page, f"Błąd synchronizacji: {ex}", ft.Colors.RED_700)
        self._page.run_task(_zrob)

    def _przywroc(self, e):
        def wykonaj():
            async def _zrob():
                try:
                    przywrocono = await asyncio.to_thread(sync.przywroc_z_chmury, self.state.auto_id)
                    utils.przejdz(self._page, "/wspoldzielenie")
                    if przywrocono:
                        utils.pokaz_komunikat(self._page, f"Przywrócono {przywrocono} rekordów z chmury.")
                    else:
                        utils.pokaz_komunikat(self._page, "Brak danych do przywrócenia — wszystko już jest na miejscu.")
                except Exception as ex:
                    utils.pokaz_komunikat(self._page, f"Błąd przywracania: {ex}", ft.Colors.RED_700)
            self._page.run_task(_zrob)

        utils.potwierdz(
            self._page,
            "Przywrócić dane z chmury?",
            "Pobierze wszystko, co jest jeszcze żywe na serwerze, a czego brakuje lokalnie. Nie cofnie usunięć, które zdążyły się już zsynchronizować.",
            wykonaj,
            tekst_potwierdzenia="Przywróć"
        )