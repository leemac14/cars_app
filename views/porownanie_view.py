import flet as ft
import flet_charts as fc
from datetime import datetime
import db
import utils

PALETA_KOLOROW = [ft.Colors.INDIGO, ft.Colors.TEAL_700, ft.Colors.ORANGE_700, ft.Colors.PURPLE_400]
MAKS_AUT = 4
SZEROKOSC_ETYKIETY = 90
SZEROKOSC_KOLUMNY = 100


class PorownanieView(ft.View):
    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state

        appbar = utils.zbuduj_pasek_z_powrotem(page, "Porównanie pojazdów", "/", ikona=ft.Icons.BALANCE)

        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT id, nazwa FROM samochody ORDER BY nazwa")
            self.wszystkie_auta = c.fetchall()

        wszystkie_id = {a[0] for a in self.wszystkie_auta}
        zapamietane = [aid for aid in (getattr(self.state, "porownanie_wybrane", None) or []) if aid in wszystkie_id]
        if not zapamietane:
            # Pierwsza wizyta / puste zapamiętane — proponujemy domyślnie kilka pierwszych aut
            zapamietane = [a[0] for a in self.wszystkie_auta[:min(3, len(self.wszystkie_auta))]]
        self.wybrane = zapamietane
        self.state.porownanie_wybrane = self.wybrane

        elementy = []

        if len(self.wszystkie_auta) < 2:
            elementy.append(utils.ekran_braku_danych(
                ikona=ft.Icons.COMPARE_ARROWS,
                tytul="Potrzebujesz co najmniej 2 pojazdów",
                opis="Dodaj kolejny pojazd do garażu, aby porównać koszty, spalanie, przebieg i terminy między autami.",
                tekst_przycisku="Dodaj pojazd",
                on_click=lambda e: utils.przejdz(self._page, "/auto/nowy")
            ))
        else:
            elementy.append(self._buduj_selektor())

            dane_aut = []
            for aid in self.wybrane:
                d = db.pobierz_dane_do_porownania(aid)
                if d:
                    d["auto_id"] = aid
                    d["kolor"] = PALETA_KOLOROW[len(dane_aut) % len(PALETA_KOLOROW)]
                    d["nazwa_wyswietlana"] = str(d.get("nazwa") or "Pojazd")
                    dane_aut.append(d)

            if len(dane_aut) < 2:
                elementy.append(
                    ft.Container(
                        padding=30,
                        content=ft.Column([
                            ft.Icon(ft.Icons.TOUCH_APP, size=48, color=ft.Colors.with_opacity(0.3, ft.Colors.PRIMARY)),
                            ft.Container(height=8),
                            ft.Text(
                                "Zaznacz co najmniej 2 pojazdy powyżej, aby zobaczyć porównanie.",
                                color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER
                            )
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)
                    )
                )
            else:
                elementy.append(self._buduj_karty_profili(dane_aut))
                elementy.append(self._buduj_werdykt(dane_aut))
                elementy.append(self._sekcja_radar(dane_aut))
                elementy.append(self._sekcja_specyfikacja(dane_aut))
                elementy.append(self._sekcja_przebieg(dane_aut))
                elementy.append(self._sekcja_koszty(dane_aut))
                elementy.append(self._sekcja_spalanie(dane_aut))
                elementy.append(self._sekcja_serwis(dane_aut))
                elementy.append(self._sekcja_terminy(dane_aut))

        elementy.append(utils.dol_bezpieczny(10))

        super().__init__(
            route="/porownanie",
            padding=15, spacing=15, scroll=ft.ScrollMode.AUTO,
            appbar=appbar, controls=elementy
        )

    # ================= SELEKTOR POJAZDÓW =================
    def _buduj_selektor(self):
        def przelacz(aid):
            if aid in self.wybrane:
                self.wybrane.remove(aid)
            elif len(self.wybrane) >= MAKS_AUT:
                utils.pokaz_komunikat(self._page, f"Można porównać maksymalnie {MAKS_AUT} pojazdy naraz.", ft.Colors.ORANGE_700)
                return
            else:
                self.wybrane.append(aid)
            self.state.porownanie_wybrane = self.wybrane
            utils.przejdz(self._page, "/porownanie")

        chipy = []
        for aid, anazwa in self.wszystkie_auta:
            zaznaczone = aid in self.wybrane
            pelny_limit = (not zaznaczone) and (len(self.wybrane) >= MAKS_AUT)
            kolor = PALETA_KOLOROW[self.wybrane.index(aid) % len(PALETA_KOLOROW)] if zaznaczone else ft.Colors.ON_SURFACE_VARIANT

            chipy.append(
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.CHECK_CIRCLE if zaznaczone else ft.Icons.DIRECTIONS_CAR, size=15,
                                color=ft.Colors.WHITE if zaznaczone else kolor),
                        ft.Text(str(anazwa), size=12, weight="bold", color=ft.Colors.WHITE if zaznaczone else kolor, no_wrap=True)
                    ], spacing=4, tight=True),
                    padding=ft.Padding(12, 8, 12, 8),
                    border_radius=20,
                    bgcolor=kolor if zaznaczone else ft.Colors.with_opacity(0.06, ft.Colors.ON_SURFACE),
                    border=ft.Border.all(1, kolor if zaznaczone else ft.Colors.with_opacity(0.2, ft.Colors.ON_SURFACE)),
                    opacity=0.4 if pelny_limit else 1.0,
                    animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
                    on_click=lambda e, a=aid: przelacz(a)
                )
            )

        return ft.Column([
            ft.Text(f"Wybierz pojazdy do porównania (2–{MAKS_AUT}):", size=13, weight="bold", color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Row(chipy, wrap=True, spacing=8, run_spacing=8)
        ], spacing=8)

    # ================= KARTY PROFILOWE =================
    def _buduj_karty_profili(self, dane_aut):
        karty = []  # <-- ZMIANA: usunięto ft.Container(width=SZEROKOSC_ETYKIETY)
        for d in dane_aut:
            zdjecie = d.get("zdjecie_glowne")
            if zdjecie:
                wizerunek = ft.Image(src=utils.abs_zalacznik(zdjecie), height=70, width=150, fit="cover", border_radius=10)
            else:
                wizerunek = ft.Container(
                    height=70, width=150, border_radius=10,
                    bgcolor=ft.Colors.with_opacity(0.12, d["kolor"]),
                    alignment=ft.Alignment.CENTER,
                    content=ft.Icon(ft.Icons.DIRECTIONS_CAR, size=30, color=d["kolor"])
                )

            def usun(e, aid=d["auto_id"]):
                if aid in self.wybrane:
                    self.wybrane.remove(aid)
                self.state.porownanie_wybrane = self.wybrane
                utils.przejdz(self._page, "/porownanie")

            karty.append(
                ft.Container(
                    width=SZEROKOSC_KOLUMNY, padding=10, border_radius=14,
                    bgcolor=ft.Colors.with_opacity(0.03, ft.Colors.ON_SURFACE),
                    border=ft.Border.all(2, d["kolor"]),
                    content=ft.Column([
                        wizerunek,
                        ft.Row([
                            ft.Column([
                                ft.Text(d["nazwa_wyswietlana"], weight="bold", size=13, no_wrap=True),
                                ft.Text(str(d.get("nr_rej") or "Brak rej."), size=11, color=ft.Colors.ON_SURFACE_VARIANT)
                            ], spacing=2, expand=True),
                            ft.IconButton(
                                ft.Icons.CLOSE, icon_size=16, icon_color=ft.Colors.ON_SURFACE_VARIANT,
                                tooltip="Usuń z porównania", on_click=usun, style=ft.ButtonStyle(padding=0)
                            )
                        ], vertical_alignment=ft.CrossAxisAlignment.CENTER)
                    ], spacing=8)
                )
            )
            
        # ZMIANA: Opakowanie w kontener z dolnym paddingiem na scrollbar
        return ft.Container(
            content=ft.Row(karty, spacing=10, scroll=ft.ScrollMode.ALWAYS),
            padding=ft.Padding(0, 0, 0, 15)
        )

    # ================= WERDYKT =================
    def _buduj_werdykt(self, dane_aut):
        pozycje = []

        z_kosztem = [d for d in dane_aut if d.get("koszt_km") is not None]
        if z_kosztem:
            best = min(z_kosztem, key=lambda d: d["koszt_km"])
            pozycje.append((ft.Icons.ACCOUNT_BALANCE_WALLET, "Najtańszy w eksploatacji", best, f"{utils.formatuj_liczba(best['koszt_km'], 2)} {utils.symbol_waluty()}/km"))

        ze_spalaniem = [d for d in dane_aut if d.get("spalanie")]
        if ze_spalaniem:
            best = min(ze_spalaniem, key=lambda d: d["spalanie"])
            pozycje.append((ft.Icons.LOCAL_GAS_STATION, "Najniższe spalanie", best, utils.formatuj_spalanie(best["spalanie"])))

        najnizszy_prz = min(dane_aut, key=lambda d: d["aktualny_przebieg"] or 0)
        pozycje.append((ft.Icons.ADD_ROAD, "Najniższy przebieg", najnizszy_prz, f"{utils.formatuj_liczba(najnizszy_prz['aktualny_przebieg'], 0)} km"))

        najspokojniejszy = min(dane_aut, key=lambda d: (d["przeterminowane"] * 10 + d["pilne"]))
        if najspokojniejszy["przeterminowane"] == 0 and najspokojniejszy["pilne"] == 0:
            pozycje.append((ft.Icons.TASK_ALT, "Brak zaległości serwisowych", najspokojniejszy, "Wszystko na czas"))

        if not pozycje:
            return ft.Container()

        wiersze = []
        for ikona, etykieta, d, wartosc_tekst in pozycje:
            wiersze.append(
                ft.Row([
                    ft.Icon(ikona, size=20, color=d["kolor"]),
                    ft.Column([
                        ft.Text(etykieta, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.Text(f"{d['nazwa_wyswietlana']} • {wartosc_tekst}", size=14, weight="bold", color=d["kolor"])
                    ], spacing=0, expand=True)
                ], spacing=10)
            )

        return ft.Container(
            padding=18, border_radius=16,
            bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.PRIMARY),
            content=ft.Column([
                ft.Row([ft.Icon(ft.Icons.EMOJI_EVENTS, color=ft.Colors.AMBER_700), ft.Text("Werdykt", weight="bold", size=16, color=ft.Colors.PRIMARY)], spacing=8),
                ft.Divider(height=15),
                ft.Column(wiersze, spacing=12)
            ])
        )

    # ================= WSPÓLNE ELEMENTY TABEL =================
    def _naglowek_kolumn(self, dane_aut):
        kolumny = [ft.Container(width=SZEROKOSC_ETYKIETY)]
        for d in dane_aut:
            kolumny.append(
                ft.Container(
                    width=SZEROKOSC_KOLUMNY, alignment=ft.Alignment.CENTER,
                    content=ft.Column([
                        ft.Container(width=10, height=10, border_radius=5, bgcolor=d["kolor"]),
                        ft.Text(d["nazwa_wyswietlana"], size=9, weight="bold", color=d["kolor"], text_align=ft.TextAlign.CENTER, no_wrap=True)
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2)
                )
            )
        return ft.Row(kolumny, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def _wiersz_tekstowy(self, etykieta, dane_aut, pobierz_wartosc, pobierz_kolor=None, ikona=None):
        podpis = ft.Text(etykieta, size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        tresc_etykiety = podpis if not ikona else ft.Row(
            [ft.Icon(ikona, size=14, color=ft.Colors.ON_SURFACE_VARIANT), podpis], spacing=4, tight=True
        )
        kolumny = [ft.Container(tresc_etykiety, width=SZEROKOSC_ETYKIETY)]
        for d in dane_aut:
            wartosc = pobierz_wartosc(d)
            kolor = pobierz_kolor(d) if pobierz_kolor else ft.Colors.ON_SURFACE
            kolumny.append(
                ft.Container(
                    width=SZEROKOSC_KOLUMNY, alignment=ft.Alignment.CENTER,
                    content=ft.Text(
                        str(wartosc) if wartosc not in (None, "") else "-",
                        size=12, weight="bold", color=kolor, text_align=ft.TextAlign.CENTER
                    )
                )
            )
        return ft.Row(kolumny, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def _pasek_porownania(self, etykieta, wpisy, jednostka="", odwrocone=False, decimale=0):
        """wpisy: lista (nazwa, wartosc, kolor_auta). Rysuje poziome paski dla każdego pojazdu,
        podświetlając na zielono najlepszy i na czerwono najgorszy wynik."""
        liczby = [w for _, w, _ in wpisy if w is not None]
        maks = max(liczby) if liczby else 0
        najlepsza = (min(liczby) if odwrocone else max(liczby)) if liczby else None
        najgorsza = (max(liczby) if odwrocone else min(liczby)) if liczby else None
        wielu_wynikow = najlepsza != najgorsza

        wiersze = []
        for nazwa, wartosc, kolor_auta in wpisy:
            if wartosc is None:
                wiersze.append(ft.Column([
                    ft.Row([
                        ft.Text(nazwa, size=12, weight="bold", expand=True, no_wrap=True),
                        ft.Text("Brak danych", size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT)
                    ]),
                    ft.ProgressBar(value=0, color=ft.Colors.ON_SURFACE_VARIANT,
                                   bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE), height=8, border_radius=4)
                ], spacing=4))
                continue

            proporcja = (wartosc / maks) if maks > 0 else 0
            if wielu_wynikow and wartosc == najlepsza:
                pasek_kolor, znacznik = ft.Colors.GREEN_700, ""
            elif wielu_wynikow and wartosc == najgorsza:
                pasek_kolor, znacznik = ft.Colors.RED_700, ""
            else:
                pasek_kolor, znacznik = kolor_auta, ""

            wiersze.append(utils.pasek_postepu(
                nazwa, f"{utils.formatuj_liczba(wartosc, decimale)} {jednostka}{znacznik}", proporcja, pasek_kolor
            ))

        return ft.Column([
            ft.Text(etykieta, size=13, weight="bold", color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Column(wiersze, spacing=10)
        ], spacing=8)

    # ================= SEKCJE =================
    def _sekcja_specyfikacja(self, dane_aut):
        tabela = ft.Column([
            self._naglowek_kolumn(dane_aut),
            ft.Divider(height=1),
            self._wiersz_tekstowy("Rocznik", dane_aut, lambda d: d.get("rok_produkcji")),
            self._wiersz_tekstowy("Silnik", dane_aut, lambda d: f"{d['pojemnosc_silnika']} cm³" if d.get("pojemnosc_silnika") else None),
            self._wiersz_tekstowy("Moc", dane_aut, lambda d: f"{d['moc_silnika']} KM" if d.get("moc_silnika") else None),
            self._wiersz_tekstowy("Paliwo", dane_aut, lambda d: d.get("typ_paliwa")),
            self._wiersz_tekstowy("Skrzynia", dane_aut, lambda d: d.get("skrzynia_biegow")),
        ], spacing=10)
        return utils.karta_formularza([ft.Row([ft.Container(content=tabela, padding=ft.Padding.only(bottom=50))], scroll=ft.ScrollMode.ALWAYS)], "Specyfikacja techniczna", ft.Icons.SETTINGS, domyslnie_otwarte=True)

    # ================= RADAR / SPIDER =================
    def _wiek_lat(self, rok):
        try:
            wiek = datetime.now().year - int(rok)
            return wiek if wiek >= 0 else None
        except (TypeError, ValueError):
            return None

    def _osie_radaru(self):
        """Definicje osi radaru: (etykieta, jednostka, funkcja wartości,
        funkcja formatująca, czy_mniej_znaczy_lepiej).

        Wartości są BEZWZGLĘDNE — w tabeli pod wykresem widać realne liczby w
        swoich jednostkach. Sam wielokąt musi jednak dzielić jedną skalę
        promienia, więc każdą oś skalujemy do jej WŁASNEGO maksimum wśród
        porównywanych aut (100% promienia = najwyższa wartość na tej osi).
        Bez tego oś „Kondycja” (0-100 pkt) zjadłaby oś „Koszt/km” (ok. 1 zł) i
        wykres byłby nieczytelny."""
        return [
            ("Koszt / km", f"{utils.symbol_waluty()}/km",
             lambda d: d.get("koszt_km"),
             lambda v: f"{utils.formatuj_liczba(v, 2)} {utils.symbol_waluty()}",
             True),
            ("Spalanie", db.pobierz_jednostke_spalania(),
             lambda d: d.get("spalanie"),
             lambda v: utils.formatuj_spalanie(v),
             True),
            ("Kondycja", "pkt",
             lambda d: d.get("kondycja"),
             lambda v: f"{utils.formatuj_liczba(v, 0)}/100",
             False),
            ("Wiek", "lat",
             lambda d: self._wiek_lat(d.get("rok_produkcji")),
             lambda v: f"{utils.formatuj_liczba(v, 0)} lat",
             True),
        ]

    def _sekcja_radar(self, dane_aut):
        osie = self._osie_radaru()

        # Oś bez ani jednej wartości nic nie wnosi — a fl_chart i tak wymaga
        # min. 3 wierzchołków, więc przy zbyt ubogich danych rezygnujemy.
        wartosci = {}   # etykieta osi -> {auto_id: wartosc}
        aktywne = []
        for etykieta, jednostka, pobierz, formatuj, mniej_lepiej in osie:
            kolumna = {}
            for d in dane_aut:
                v = pobierz(d)
                try:
                    v = float(v) if v is not None else None
                except (TypeError, ValueError):
                    v = None
                kolumna[d["auto_id"]] = v if (v is not None and v > 0) else None
            if any(v is not None for v in kolumna.values()):
                aktywne.append((etykieta, jednostka, formatuj, mniej_lepiej))
                wartosci[etykieta] = kolumna

        if len(aktywne) < 3:
            return utils.karta_formularza(
                [ft.Text(
                    "Za mało danych na radar — potrzeba wartości w co najmniej 3 z 4 kategorii "
                    "(koszt/km, spalanie, kondycja, wiek) dla porównywanych pojazdów.",
                    size=12, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
                )],
                "Radar porównawczy", ft.Icons.RADAR
            )

        maksima = {
            etykieta: max((v for v in wartosci[etykieta].values() if v is not None), default=0)
            for etykieta, _, _, _ in aktywne
        }

        SKALA = 100.0
        zestawy = []
        for d in dane_aut:
            punkty = []
            for etykieta, _, _, _ in aktywne:
                v = wartosci[etykieta].get(d["auto_id"])
                maks = maksima[etykieta] or 0
                # Brak danych rysujemy jako 0 (wierzchołek w środku) — tabela
                # pod wykresem mówi wprost, że to „brak”, a nie zero.
                udzial = (v / maks * SKALA) if (v is not None and maks > 0) else 0.0
                punkty.append(fc.RadarDataSetEntry(value=round(udzial, 2)))

            zestawy.append(fc.RadarDataSet(
                entries=punkty,
                fill_color=ft.Colors.with_opacity(0.16, d["kolor"]),
                border_color=d["kolor"],
                border_width=2,
                entry_radius=3,
            ))

        kolor_siatki = ft.Colors.with_opacity(0.20, ft.Colors.ON_SURFACE)
        tytuly = []
        for etykieta, jednostka, formatuj, mniej_lepiej in aktywne:
            strzalka = "↓" if mniej_lepiej else "↑"
            tytuly.append(fc.RadarChartTitle(text=f"{etykieta} {strzalka}"))

        wykres = fc.RadarChart(
            data_sets=zestawy,
            titles=tytuly,
            title_text_style=ft.TextStyle(size=10, color=ft.Colors.ON_SURFACE_VARIANT),
            title_position_percentage_offset=0.12,
            radar_shape=fc.RadarShape.POLYGON,
            radar_bgcolor=ft.Colors.TRANSPARENT,
            radar_border_side=ft.BorderSide(width=1, color=kolor_siatki),
            grid_border_side=ft.BorderSide(width=1, color=kolor_siatki),
            tick_border_side=ft.BorderSide(width=1, color=ft.Colors.with_opacity(0.10, ft.Colors.ON_SURFACE)),
            tick_count=4,
            # Podziałki „w procentach lidera osi” tylko myliłyby przy wartościach
            # bezwzględnych — chowamy je, liczby są w tabeli niżej.
            ticks_text_style=ft.TextStyle(size=9, color=ft.Colors.TRANSPARENT),
            interactive=False,
            expand=True,
        )

        legenda = ft.Row(
            [
                ft.Row([
                    ft.Container(width=10, height=10, border_radius=5, bgcolor=d["kolor"]),
                    ft.Text(d["nazwa_wyswietlana"], size=11, weight="bold", color=d["kolor"], no_wrap=True),
                ], spacing=5, tight=True)
                for d in dane_aut
            ],
            wrap=True, spacing=12, run_spacing=6,
        )

        # Tabela wartości BEZWZGLĘDNYCH — to ona jest źródłem prawdy o liczbach,
        # radar pokazuje wyłącznie kształt profilu pojazdu.
        wiersze_tabeli = [self._naglowek_kolumn(dane_aut), ft.Divider(height=1)]
        for etykieta, jednostka, formatuj, mniej_lepiej in aktywne:
            kolumna = wartosci[etykieta]
            dostepne = [v for v in kolumna.values() if v is not None]
            najlepsza = (min(dostepne) if mniej_lepiej else max(dostepne)) if dostepne else None
            wielu = len(set(dostepne)) > 1

            def tekst(d, _k=kolumna, _f=formatuj):
                v = _k.get(d["auto_id"])
                return _f(v) if v is not None else "Brak"

            def kolor(d, _k=kolumna, _n=najlepsza, _w=wielu):
                v = _k.get(d["auto_id"])
                if v is None:
                    return ft.Colors.ON_SURFACE_VARIANT
                return ft.Colors.GREEN_700 if (_w and _n is not None and v == _n) else ft.Colors.ON_SURFACE

            strzalka = "↓" if mniej_lepiej else "↑"
            wiersze_tabeli.append(
                self._wiersz_tekstowy(f"{etykieta} {strzalka}", dane_aut, tekst, pobierz_kolor=kolor)
            )

        tabela = ft.Column(wiersze_tabeli, spacing=10)

        opis = ft.Text(
            "Wartości są bezwzględne (patrz tabela). Na wykresie każda oś ma własną skalę — "
            "krawędź to najwyższa wartość danej osi wśród porównywanych aut, środek to zero. "
            "↓ = mniej znaczy lepiej, ↑ = więcej znaczy lepiej, więc większy wielokąt NIE oznacza "
            "automatycznie lepszego auta.",
            size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
        )

        return utils.karta_formularza(
            [
                legenda,
                ft.Container(height=270, padding=ft.Padding(10, 18, 10, 10), content=wykres),
                opis,
                ft.Divider(height=15),
                ft.Row([ft.Container(content=tabela, padding=ft.Padding.only(bottom=50))], scroll=ft.ScrollMode.ALWAYS),
            ],
            "Radar porównawczy", ft.Icons.RADAR, domyslnie_otwarte=True
        )

    def _wiek_tekst(self, rok):
        try:
            wiek = datetime.now().year - int(rok)
            if wiek < 0:
                return None
            return "1 rok" if wiek == 1 else f"{wiek} lat"
        except (TypeError, ValueError):
            return None

    def _sekcja_przebieg(self, dane_aut):
        pasek = self._pasek_porownania(
            "Aktualny przebieg",
            [(d["nazwa_wyswietlana"], d["aktualny_przebieg"], d["kolor"]) for d in dane_aut],
            "km", odwrocone=True, decimale=0
        )
        tabela = ft.Column([
            self._naglowek_kolumn(dane_aut),
            self._wiersz_tekstowy("Śr. dziennie", dane_aut, lambda d: f"{utils.formatuj_liczba(d['sredni_dzienny'], 1)} km" if d.get("sredni_dzienny") else "Brak danych"),
            self._wiersz_tekstowy("Wiek pojazdu", dane_aut, lambda d: self._wiek_tekst(d.get("rok_produkcji"))),
        ], spacing=10)
        
        return utils.karta_formularza([pasek, ft.Divider(height=15), ft.Row([ft.Container(content=tabela, padding=ft.Padding.only(bottom=50))], scroll=ft.ScrollMode.ALWAYS)], "Przebieg i wiek", ft.Icons.SPEED, domyslnie_otwarte=True)

    def _sekcja_koszty(self, dane_aut):
        pasek_calkowity = self._pasek_porownania(
            "Koszt całkowity (od początku)",
            [(d["nazwa_wyswietlana"], d["koszt_razem"], d["kolor"]) for d in dane_aut],
            utils.symbol_waluty(), odwrocone=True, decimale=0
        )
        pasek_km = self._pasek_porownania(
            "Koszt eksploatacji na 1 km",
            [(d["nazwa_wyswietlana"], d["koszt_km"], d["kolor"]) for d in dane_aut],
            f"{utils.symbol_waluty()}/km", odwrocone=True, decimale=2
        )
        tabela = ft.Column([
            self._naglowek_kolumn(dane_aut),
            self._wiersz_tekstowy("Paliwo", dane_aut, lambda d: f"{utils.formatuj_liczba(d['koszt_paliwo'], 0)} {utils.symbol_waluty()}",
                                  ikona=utils.IKONY_KATEGORII_KOSZTOW["paliwo"]),
            self._wiersz_tekstowy("Serwis", dane_aut, lambda d: f"{utils.formatuj_liczba(d['koszt_serwis'], 0)} {utils.symbol_waluty()}",
                                  ikona=utils.IKONY_KATEGORII_KOSZTOW["serwis"]),
            self._wiersz_tekstowy("Inne", dane_aut, lambda d: f"{utils.formatuj_liczba(d['koszt_inne'], 0)} {utils.symbol_waluty()}",
                                  ikona=utils.IKONY_KATEGORII_KOSZTOW["inne"]),
        ], spacing=10)
        
        return utils.karta_formularza([pasek_calkowity, ft.Divider(height=15), pasek_km, ft.Divider(height=15), ft.Row([ft.Container(content=tabela, padding=ft.Padding.only(bottom=50))], scroll=ft.ScrollMode.ALWAYS)], "Koszty eksploatacji", ft.Icons.ATTACH_MONEY, domyslnie_otwarte=True)
    
    def _sekcja_spalanie(self, dane_aut):
        wartosci = [d["spalanie"] for d in dane_aut if d.get("spalanie")]
        maks = max(wartosci) if wartosci else 0
        najlepsze = min(wartosci) if wartosci else None
        najgorsze = max(wartosci) if wartosci else None

        wiersze = []
        for d in dane_aut:
            wartosc = d.get("spalanie")
            if not wartosc:
                wiersze.append(ft.Column([
                    ft.Row([
                        ft.Text(d["nazwa_wyswietlana"], size=12, weight="bold", expand=True, no_wrap=True),
                        ft.Text("Za mało danych", size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT)
                    ]),
                    ft.ProgressBar(value=0, bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE), height=8, border_radius=4)
                ], spacing=4))
                continue

            proporcja = wartosc / maks if maks > 0 else 0
            if najlepsze != najgorsze and wartosc == najlepsze:
                pasek_kolor = ft.Colors.GREEN_700
            elif najlepsze != najgorsze and wartosc == najgorsze:
                pasek_kolor = ft.Colors.RED_700
            else:
                pasek_kolor = d["kolor"]

            wiersze.append(ft.Column([
                ft.Row([
                    ft.Text(d["nazwa_wyswietlana"], size=12, weight="bold", expand=True, no_wrap=True),
                    ft.Text(utils.formatuj_spalanie(wartosc), size=12, weight="bold", color=pasek_kolor)
                ]),
                ft.ProgressBar(value=max(0.03, proporcja), color=pasek_kolor,
                               bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE), height=8, border_radius=4)
            ], spacing=4))

        opis = ft.Text("Wymaga min. 2 tankowań „do pełna” dla danego pojazdu.", size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT)
        return utils.karta_formularza([ft.Column(wiersze, spacing=10), opis], "Średnie spalanie", ft.Icons.LOCAL_GAS_STATION)

    def _sekcja_serwis(self, dane_aut):
        tabela = ft.Column([
            self._naglowek_kolumn(dane_aut),
            ft.Divider(height=1),
            self._wiersz_tekstowy("Wpisy historii", dane_aut, lambda d: str(d["liczba_wpisow_historii"])),
            self._wiersz_tekstowy("Wizyty zbiorcze", dane_aut, lambda d: str(d["liczba_wizyt"])),
            self._wiersz_tekstowy("Aktywne zadania", dane_aut, lambda d: str(d["do_zrobienia_aktywne"])),
            self._wiersz_tekstowy(
                "Zaległości", dane_aut,
                lambda d: (f"{d['przeterminowane']} po term." if d["przeterminowane"] else (f"{d['pilne']} pilne" if d["pilne"] else "Brak")),
                pobierz_kolor=lambda d: ft.Colors.RED_700 if d["przeterminowane"] else (ft.Colors.ORANGE_700 if d["pilne"] else ft.Colors.GREEN_700)
            ),
            self._wiersz_tekstowy(
                "Niski stan mag.", dane_aut,
                lambda d: (f"{d['magazyn_niski_stan']} poz." if d["magazyn_niski_stan"] else "OK"),
                pobierz_kolor=lambda d: ft.Colors.ORANGE_700 if d["magazyn_niski_stan"] else ft.Colors.GREEN_700
            ),
        ], spacing=10)
        return utils.karta_formularza([ft.Row([ft.Container(content=tabela, padding=ft.Padding.only(bottom=50))], scroll=ft.ScrollMode.ALWAYS)], "Serwis i przypomnienia", ft.Icons.BUILD_CIRCLE)

    def _kolor_i_tekst_dokumentu(self, data_str):
        try:
            d_obj = datetime.strptime(str(data_str), "%d.%m.%Y").date()
            roz = (d_obj - datetime.now().date()).days
            if roz < 0:
                return ft.Colors.RED_700, str(data_str)
            elif roz <= 30:
                return ft.Colors.ORANGE_700, str(data_str)
            return ft.Colors.GREEN_700, str(data_str)
        except Exception:
            return ft.Colors.ON_SURFACE_VARIANT, str(data_str)

    def _sekcja_terminy(self, dane_aut):
        def wiersz_terminu(etykieta, pole):
            def wartosc(d):
                data_str = d.get(pole)
                if not data_str: return "Brak"
                _, tekst = self._kolor_i_tekst_dokumentu(data_str)
                return tekst
            def kolor(d):
                data_str = d.get(pole)
                if not data_str: return ft.Colors.ON_SURFACE_VARIANT
                k, _ = self._kolor_i_tekst_dokumentu(data_str)
                return k
            return self._wiersz_tekstowy(etykieta, dane_aut, wartosc, pobierz_kolor=kolor)

        tabela = ft.Column([
            self._naglowek_kolumn(dane_aut),
            ft.Divider(height=1),
            wiersz_terminu("Polisa OC", "oc_data"),
            wiersz_terminu("Przegląd", "przeglad_data"),
            wiersz_terminu("Polisa AC", "ac_data"),
            wiersz_terminu("Assistance", "assistance_data"),
        ], spacing=10)
        return utils.karta_formularza([ft.Row([ft.Container(content=tabela, padding=ft.Padding.only(bottom=50))], scroll=ft.ScrollMode.ALWAYS)], "Ważne terminy", ft.Icons.SHIELD)