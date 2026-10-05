# tests/

Dwanaście rodzajów sprawdzeń, które i tak robiło się ręcznie po każdej zmianie —
zapisanych raz, uruchamianych zawsze.

## Uruchomienie

```
.venv\Scripts\pip install pytest
.venv\Scripts\python -m pytest
```

`pytest.ini` w korzeniu ustawia `testpaths`, więc samo `pytest` wystarczy.
Pojedynczy plik: `python -m pytest tests/test_kosz.py -q`.
Jeden test: `python -m pytest tests/test_kosz.py -k kolizja -q`.

Testy NIE dotykają `flota_zadania.db` obok repozytorium. `conftest.py` ustawia
`FLET_APP_STORAGE_DATA` na katalog tymczasowy **przed** pierwszym `import db` —
ścieżka bazy liczy się w chwili importu, więc później byłoby już za późno.

## Co jest sprawdzane

| Plik | Pilnuje |
|---|---|
| `test_migracje.py` | Baza w KAŻDEJ wersji schematu dochodzi po `init_db()` do tego samego stanu, co świeża. Dane starych wpisów przeżywają awans (rodzaj energii, status, rola, przeliczenie zakładek). Zamek na migracje już wydane. Próbki baz. Odmowa wczytania kopii z nowszym schematem. |
| `probki_baz.py` | Budowanie, zasiew i zrzut próbek. Bez pytesta. |
| `probki/schemat_NN.sql` | Zamrożone bazy — po jednej na wersję schematu, z danymi. |
| `test_kosz.py` | Round-trip pojazdu bit w bit: każdy wiersz, każda wartość, suma kontrolna każdego zdjęcia. Kolizja wszystkich ID i nazwy. Nagrobki dopiero przy trwałym kasowaniu. Retencja i sieroty. |
| `test_schemat.py` | `KONFIGURACJA_SYNC`, `KOLUMNY_POJAZDU`, `KOSZ_TABELE_*`, `KOLUMNY_ZE_SCIEZKAMI`, `POLA_NOTATKI` kontra `PRAGMA table_info` — w OBIE strony. Zapytania pośrednie i `reset_where` jako poprawny SQL. |
| `test_widoki.py` | Wszystkie widoki budują się bez okna, na dziewięciu układach danych: pusty garaż, auto bez wpisów, komplet, auto z historią, elektryk, hybryda plug-in, auto sprzedane, cudze auto w podglądzie, pełny kosz. Ekran główny osobno w każdej zakładce. |
| `test_konce_linii.py` | Cały projekt na LF, bez BOM-ów, z jawną polityką w `.gitattributes`. Umie też naprawiać. |
| `test_formatowanie.py` | Ekran i eksport składają liczbę tak samo; zaokrąglenia wypisane wprost; rozmiary w bajtach mają jedną postać. |
| `test_audyty.py` | Sześć audytów: `expand` w wierszu o nieograniczonej szerokości, chipy rozciągające się na całą linijkę paska zawijanego, pola i argumenty kontrolek Fleta + `run_task`, ciche `except …: pass`, kształt wyników `db` kontra adnotacje, ręczne składanie liczb. Plus testy samych audytów. |
| `audyty.py` | Silniki tych sześciu audytów. Da się uruchomić wprost: `python tests/audyty.py`. |
| `test_typy_db.py` | Adnotacje zwrotu warstwy danych kontra to, co funkcje naprawdę zwracają — wołane na bazie testowej. |
| `ciche_wyjatki.txt` | Zamrożona liczba cichych `except …: pass` w każdym pliku. |
| `test_start.py` | Podział startu: `init_db()` robi tylko schemat, `porzadki_startowe()` sprząta kosz, odroczone załączniki i (raz) ścieżki. |
| `test_sync_pakiet.py` | Pakiet `sync/`: zależności tylko w dół, `__init__.py` bez logiki, nazwy przypisywane przez `global` nie wychodzą z modułu, blokada sieci sięga każdego wiązania, aplikacja nie woła nazwy, której pakiet nie wystawia, obok pakietów `db/`, `utils/`, `sync/` nie leży martwy plik o tej samej nazwie. |
| `test_eksporty_pakietow.py` | Pakiety `db`, `utils`, `sync` sklejane gwiazdkowym importem: żadna nazwa nie jest wystawiana przez dwa moduły (wygrałby po cichu późniejszy — tak `db._na_liczbe` był podmieniany funkcją z wyszukiwarki) i żadna nazwa przypisywana przez `global` nie siedzi w `__all__` (pakiet trzymałby jej zamrożoną kopię). |
| `test_log.py` | Rotujący log błędów: co łapie (połknięty wyjątek, wątek, porzucona korutyna asyncio, cudze ostrzeżenia), czego nie łapie (cudze INFO), rotacja, raport do wysłania i to, że brak miejsca na log nie wywala aplikacji. |
| `test_magazyn_koszt.py` | Koszt części z magazynu w koszcie serwisu, przez prawdziwe formularze: nowy wpis i wizyta, edycja bez podwójnego doliczenia i po cenie zapamiętanej przy rekordzie, duplikat bez kosztu części, usunięcie z cofnięciem. Migracja 41 bez doliczania wstecz. Wartość magazynu, historia zużycia, ostrzeżenie przy usuwaniu, przeliczanie ceny w formularzu pozycji, średnia cena po scaleniu duplikatów. |
| `test_robocizna_czesci.py` | Robocizna osobno od części przy wizycie i pojedynczym wpisie. Rozbicie z dwóch zapisanych liczb zawsze się sumuje — także po zwrocie pozycji wizyty (różnica schodzi z części, cofnięcie wraca) i po usunięciu pozycji magazynu. Migracja 42 zostawia stare naprawy bez podziału. Synchronizacja: pusta kolumna z `dopisane` nie zmienia rekordu, więc pierwsza synchronizacja po aktualizacji nic nie wysyła, drugi telefon nie widzi fałszywych konfliktów, a prawdziwy konflikt zostaje konfliktem. Formularze: nowa wizyta od razu z podziałem, z magazynem w podsumowaniu, edycja i duplikat z tymi samymi kwotami, stara wizyta rozbijana jedną liczbą (części maleją o wpisywaną robociznę, dopóki ich nie poprawisz), przełączanie bez gubienia kwoty, ujemna kwota, wymiana zrobiona samemu. Karty i filtr „Podział” na liście wizyt i w historii podzespołu. Rozbicie w okresie z warsztatami, porównanie części z warsztatu i z magazynu tylko z napraw jednego podzespołu, obserwacje w obie strony, karta w Analizie, kolumny w CSV i PDF. |
| `test_role_ukrywanie.py` | Rola pojazdu a interfejs i nagrobki. Menu wpisu odsiewane przez `utils.odsiej_akcje`: właściciel widzi wszystko, podgląd tylko pozycje oznaczone `czyta`, a menu bez takich pozycji tłumaczy się jedną linijką bez akcji. Pozycja bez flagi znika (domyślnie zamknięte). Współautor per wpis — swoje tankowanie tak, cudze nie, wspólny inwentarz (magazyn) tak. Kosz w pasku zaznaczania: jest przy pełnych prawach i u współautora, znika przy podglądzie. Nagrobki ze ścieżki zbiorczej i pojedynczej dostają `auto_id` (historia — JOIN-em przez podzespół, części wpisu dziedziczą jego pojazd), więc usunięcie z auta A nie leci przy synchronizacji auta B; nagrobek bez pojazdu leci dalej przy każdym. Cofnięcie kasuje nagrobki, a db odmawia grupowego usuwania przy podglądzie. |
| `test_powiadomienia.py` | Interwał podzespołu jako dwa liczniki i jeden termin: który przyjdzie pierwszy (z prognozą i bez średniej), licznik po terminie, status jako najgorszy z obu, własny próg podzespołu, zdania zgodne z liczbą. Jedno powiadomienie na podzespół, karta w Serwisie z oboma licznikami i znacznikiem „najpierw”. „Widziane” per powiadomienie: zmiana treści nie jest nowością, pogorszenie jest, zniknięty powód wraca jako nowy, osobno dla każdego auta, przetrwanie zimnego startu i kosza, dzwonek liczący tylko nowe, pigułka „nowe” w panelu. |
| `test_kondycja.py` | Kondycja po przeważeniu tabeli kar. Dokumenty: OC i przegląd po terminie bolą mocniej niż podzespół, oba naraz dają „wymaga pilnej reakcji”, zbliżający się termin mniej, daleki wcale, koniec gwarancji wcale, a waga rośnie z konsekwencjami (apteczka < AC < OC). Terminy liczone stałym wyprzedzeniem, więc próg powiadomień z ustawień kondycji nie rusza. Sufity grup: sześć zaległych podzespołów liczone jako limit grupy, grupa w limicie nieprzycinana, „odjęte” zgodne z wynikiem. Licznik: cofka w rozpisce, seria cofek przycięta do sufitu. Dane: dwa progi ciszy z datą ostatniego wpisu, brak terminu OC/przeglądu, brak historii licznika, sprzedane auto bez kar za ciszę i braki. Usterki: zaległa pozycja o najwyższym priorytecie karana, plany i drobiazgi nie. Odłożone powiadomienie nadal nie naprawia auta. Panel rozpiski pokazuje dokument, sumę i przyznaje się do sufitu. |
| `test_wyszukiwarka_ekranow.py` | Gdzie wyszukiwarka stawia ekrany: przy frazie krótszej niż 4 znaki albo bez trafień we wpisy wszystkie nad wpisami; przy dłuższej z trafieniami każdy osobno — trafienie w tytuł zostaje u góry, trafienie tylko w opis albo słowa pomocnicze schodzi pod wpisy. Rozstawienie niczego nie gubi i trzyma wspólny limit. Słowa pomocnicze tylko od początku słowa, tytuły dowolnym fragmentem. Kwota i krótka fraza chowają obie sekcje. |
| `test_wyszukiwarka_zapytania.py` | Zapytania datowe („marzec 2026”, „ostatni tydzień”, zakresy, „rok 2026”), operatory pól (`stacja:`, `tag:`, `kategoria:`, `typ:` i aliasy) oraz ich łączenie z kwotą i resztą tekstu. Cichy powrót do szukania tekstowego tam, gdzie nic nie pasuje („listwa”, „opony 205”, „31.02.2026”). Zgodność wsteczna ścieżki kwotowej. Wyniki na bazie testowej, pasek trybu i chipy składni na ekranie /szukaj. |
| `test_historia_wyszukiwan.py` | Ostatnie wyszukiwania: kolejność i limit listy, dłuższa fraza wypierająca swój początek („marzec” → „marzec 2026”), duplikaty, kasowanie pojedynczej frazy i całej listy, wyłączony przełącznik. Na ekranie /szukaj: chipy tylko przy pustym polu, zapis przy otwarciu wyniku i przy filtrze z wynikami, cisza przy frazie bez wyników, chip powtarzający wyszukiwanie, długie przytrzymanie i „Wyczyść”. |
| `test_sciezki_zalacznikow.py` | Ścieżki załączników w bazie zawsze względne (`zalaczniki/<nazwa>`), sklejane ze `STORAGE_PATH` przy odczycie. Postać do bazy z każdego zapisu (tutejszy, Android, Windows, `\`), odczyt dawnych formatów bez migracji, plik odroczony nie „znajduje się” po nazwie. Nowy załącznik, zatwierdzenie i anulowanie. Sześć usunięć z cofnięciem odkłada i oddaje plik. Kosz pamięta pliki względnie. Kopia na urządzeniu z innym `STORAGE_PATH` działa bez naprawy, a dawna pozycja kosza z obcymi ścieżkami przeżywa sprzątanie sierot i wraca ze ścieżkami względnymi. Raport PDF widzi zdjęcia. |
| `test_metryki_sprzedanego.py` | Metryki sprzedanego auta liczone na dzień sprzedaży, nie na dzisiaj: okres posiadania, okno wydatków, koszt miesięczny, wiek i tempo jazdy. Brak daty, data z przyszłości i data sprzed zakupu wracają do zachowania sprzed domknięcia. |
| `test_podzespoly_napedu.py` | Lista startowa podzespołów składana z bazy i modułu napędu: każdy typ paliwa ma swoją decyzję w mapie, elektryk dostaje to samo co przed zmianą, LPG i diesel swoje pozycje, żadna lista bez duplikatów i emoji, interwały trafiają w istniejące nazwy. Legalizacja butli jako termin (120 miesięcy, bez km) daje powiadomienie. Dopisywanie brakujących po zmianie napędu jest idempotentne i nie dubluje własnej pisowni użytkownika. Gotowe zestawy tylko przy pełnym składzie. Chipy w formularzu nowego pojazdu: przebudowa po zmianie napędu, odklikanie jako niezapisana zmiana. |
| `test_kafelki_akcji.py` | Kafelki akcji na kokpicie: sześć akcji (tankowanie, stan licznika, inny koszt, wizyta, podzespół, do zrobienia) ma własny kafelek z dotknięciem, akcje wchodzą tylko do układu domyślnego (pojazd z własnym układem zostaje nietknięty), rola „podgląd” nie dostaje ich wcale. Kafelek „Stan licznika” otwiera wspólny formularz odczytu, zapisuje przebieg bez zmiany ekranu i odświeża kokpit, a błędna wartość nie zapisuje niczego. |
| `test_ukladanie_kokpitu.py` | Układanie kafelków wprost w siatce: upuszczenie stawia kafelek na miejscu celu (w obie strony), upuszczenie na siebie i bez źródła nic nie zmienia, krzyżyk zdejmuje kafelek z kokpitu, „Dodaj kafelek” przywraca zdjęte i pokazuje wyłącznie te spoza kokpitu, w trybie układania kafelek nie otwiera ekranu, wejście z Ustawień gasi swoją flagę, a pusty kokpit nadal ma czym dodawać. |
| `test_puste_kafelki.py` | Kafelki kokpitu bez treści chowają się same: w aucie bez ani jednego wpisu znika siedem kafelków typu „nie dotyczy” (budżet, opony, checklista, magazyn, zasięg na baku, zasięg EV, opłaty drogowe), a kafelki czekające na dane („za mało danych”) zostają. Wyłączony przełącznik w Ustawieniach przywraca myślniki, kafelek z treścią nigdy nie znika, a gdy milczą wszystkie — zamiast pustej siatki wchodzi zachęta z przyciskiem „Pokaż puste”, który działa od razu. Tryb układania pokazuje schowane kafelki przygaszone, z dopiskiem. |
| `test_siatka_kokpitu.py` | Kokpit jako siatka `ResponsiveRow`, nie karuzela: w kokpicie nie ma przewijania w bok, kafelek nie trzyma własnej szerokości (liczy ją Flet z rzeczywistej szerokości ekranu), a dwa rozmiary trzymają proporcję — 2×1 to dokładnie dwie komórki 1×1 w każdym progu. Rozmiar bierze się z treści kafelka. Tryb układania wchodzi i wraca do siatki. |
| `test_trend_sezonowy.py` | Sezon w trendzie spalania: ta sama zmiana kalendarza sprzed roku odjęta od surowej zmiany. Sezonowy skok (wrzesień → listopad) nie zapala obserwacji, wzrost ponad sezon dalej zapala, wiosna bez spadku liczy się jako wzrost, pierwszy rok bez historii działa jak dawniej. Rok do roku i 29 lutego. |
| `test_zakres_wykresow.py` | Chipy zakresu czasu nad wykresami: siatka słupków wydatków (do roku miesiące, „Wszystko” przy dłuższej historii kwartały, powyżej trzech lat lata; każdy miesiąc w dokładnie jednym słupku), liczba kolumn heatmapy z sufitem, zakres zapamiętany per pojazd i per wykres (śmieć wraca do wartości domyślnej, zakresy nie przeciekają między wykresami), przejazd zakresów do kosza i z powrotem mimo zmiany ID, obcięcie krzywej cen RAZEM z rankingiem stacji, budowa podzakładki Wykresy w każdym z czterech zakresów. |
| `test_filtry_liczniki.py` | Liczniki przy chipach filtrów: liczba KRZYŻOWA (przy pozostałych filtrach ustawionych tak jak teraz), własny filtr nie zeruje swoich opcji, opcja bez pokrycia zostaje w menu z „(0)” i bez klikalności, wybrana wartość nigdy się nie blokuje, licznik na chipie zgodny z długością listy, wartość skracana przed licznikiem, zapomniany filtr wraca do „Wszystko”. Wynik `pasek_filtrow` taki sam jak dawny łańcuch `filtruj_po_*`. Autor: „Tylko moje” i „Bez autora”. |
| `test_budzety.py` | Trzeci okres budżetu — okno „ostatnie 30 dni”. Granice okna (dzień sprzed 29 jeszcze w środku, sprzed 30 już poza), wydatki z przełomu miesiąca liczone razem zamiast rozbite na dwa okresy, brak prognozy i daty przekroczenia w oknie ruchomym przy nietkniętej prognozie miesięcznej, pasek bez znacznika upływu i podpis bez „0 dni”, osobna obserwacja z nazwą okresu w treści. |
| `test_koszt_skumulowany.py` | Krzywa kosztu skumulowanego: start w cenie zakupu i przełącznik na samą eksploatację, brak daty zakupu (oś od pierwszego wpisu), wpisy sprzed zakupu poza rachunkiem, krzywa niemalejąca domykająca się sumą, cisza jako poziomy odcinek do dzisiaj. Znaczniki większych wydatków: próg trzykrotności mediany, sufit sześciu, równe wpisy bez znacznika, znacznik siedzi na krzywej. Sprzedane auto zamknięte dniem sprzedaży z odliczeniem ceny sprzedaży. Koszt na dzień i na kilometr. Zakres czasu przycina widok, nie rachunek; karta bez wydatków mówi, czego brakuje; kafelek kokpitu. |
| `test_koszt_1000km.py` | Koszt na 1000 km w oknie kroczącym: punkt liczony z całego okna (nie średnia ilorazów), punkt dopiero przy oknie mieszczącym się w danych, większy przebieg przy proporcjonalnych kosztach nie rusza ceny jazdy, drożejące auto widać w oknie i rok do roku (rok do roku wymaga dwóch pełnych okien), krótsze okno reaguje szybciej, kategorie sumują się do razem, średnia życiowa z tej samej historii. Okno zapamiętane per pojazd w jednym wierszu z zakresami wykresów. Oś wykresu od zera plus linia odniesienia, karta, kafelek kokpitu, obserwacja „Auto drożeje”/„Auto tanieje” (stabilne auto milczy), cena jazdy w Roku w pigułce i w porównaniu pojazdów. |
| `test_kolory_tagow.py` | Kolory tagów: napis na każdym kolorze palety czytelny (kontrast WCAG ≥ 4,5:1, ciemny na żółtym, biały na indygo), kolor #RRGGBB z danych też działa, nieznany = brak koloru. Tag trafia w kolor niezależnie od pisowni we wpisie, tag spoza słownika dostaje obwódkę zamiast udawanego niebieskiego, nowy tag dostaje pierwszy wolny kolor. Karty Innych kosztów i Tankowań, filtr „Tagi” (kółka w menu, włączony chip w kolorze tagu, odsiewanie jak kategoria, nowy filtr na Innych kosztach za Kategorią), wyniki wyszukiwarki (tagi zamiast dopisku w opisie, chipy na karcie). Edytor: pisownia ze słownika, tag spoza słownika widoczny i do pokolorowania przytrzymaniem, kółka bez „Brak”, kolor spoza palety nie ginie przy zapisie. |
| `test_rok_do_roku.py` | Dwie krzywe lat na jednej osi miesięcy: obie po dwanaście pozycji, rok w toku urwany na bieżącym miesiącu i porównywany z tymi SAMYMI miesiącami roku poprzedniego, suma narastająca od stycznia, postać miesięczna odsłaniająca pojedynczy skok. Miesiąc rozjazdu wskazuje zdarzenie (w obie strony) i milczy przy różnicy narastającej stopniowo. Kilometry i cena jazdy jako wielkości — iloraz liczony z sum składników, nie jako średnia miesięcznych ilorazów; kategoria osobno; nieznana wielkość wraca do kosztów; rok bez wpisów to brak danych, a nie zero. Wykres: oś od zera, poprzedni rok przerywany, słupki różnicy. Karta mówi, w którym miesiącu się rozjechało. |
| `test_przypomnienie_licznika.py` | Przypomnienie o odczycie licznika: próg z Ustawień (29 dni nic, 30 już tak; 14/60/wyłączone; śmieć wraca do 30), każde źródło przebiegu kończy ciszę, cisza liczona z tego samego wpisu co Historia licznika, auto bez przebiegu od razu, sprzedane i podgląd bez prośby. Zdanie: od ilu dni, z jakiej liczby liczą prognozy (ta z `pobierz_aktualny_przebieg`) i ile mogło przybyć. Za prawdziwymi terminami na liście. Okresy ciszy: nowy okres = nowy klucz, więc odznaka zapala się znowu; drzemka pod kluczem cyklu trwa mimo nowego okresu, a nowy wpis zaczyna cykl bez starej drzemki. Porównanie i kondycja go nie liczą. Panel („Wpisz stan”, ptaszek, drzemka pod kluczem cyklu), dopisek „sprzed N dni” w nagłówku, pasek w Serwisie (bez przycisku przy podglądzie, cisza bez interwałów km), pasek w Historii licznika, zapis progu w Ustawieniach. |
| `test_rozliczenia.py` | Saldo współdzielonego auta i „Rozliczone”: dwie osoby i jeden przelew, osoba bez wpisów też ponosi część (ja przy aucie, nie przy podglądzie), wizyta raz, a jej wpisy wcale, wydatki bez podpisu poza saldem, podpis bez wielkości liter i spacji (także w zestawieniu miesiąca). Rozliczenie zeruje saldo co do grosza przy nierównym podziale, suma sald jest zawsze zerem. Rozliczenie to migawka, nie data odcięcia: wpis sprzed niego dopisany, poprawiony albo usunięty później wchodzi do salda jako korekta; rozliczenie z datą wstecz zostawia późniejsze wpisy; data nie z przyszłości ani sprzed poprzedniego; nowy domownik nie płaci za zamknięty okres. Cofnąć można tylko ostatnie (i cofnięcie się cofa), współautor tylko swoje; dwa „Rozliczone” naraz liczą się raz. Chmura: rozliczenie dochodzi do drugiego telefonu i zeruje tam saldo bez odsyłania, dwa telefony naraz dają to samo saldo, cofnięcie zostawia nagrobek; kosz oddaje rozliczenia z tym samym saldem. Ekran: saldo, kto komu ile, przycisk, okno z podglądem przelewów i walidacją daty, cofanie z historii, podgląd bez przycisków, uwagi o jednej osobie i wpisach bez podpisu, audyty drzewa. |
| `test_poprawki_przegladu.py` | Poprawki z przeglądu kodu. Podejrzany przebieg: wpis bez licznika nie udaje ostatniego stanu, wpis wsteczny porównywany z sąsiadami w czasie. Paliwo i prąd osobno: trend cen i ranking stacji plug-ina, obserwacja stacji, spalanie w porównaniu pojazdów, zużycie elektryka w Roku w pigułce i w PDF, „kWh” na osi czasu; wpis bez licznika nie psuje dystansu ani odcinków spalania. Tagi: zmiana nazwy i usunięcie trafiają w każdą pisownię, bez dubli, z odmową kolizji; edytor zachowuje kolejność. Rok w toku porównywany z tym samym okresem roku poprzedniego, „prawie” tylko przy braku do dystansu. Edycja wizyty poprawia pozycje zamiast zakładać je od nowa. Odmiana przez liczbę, parsowanie liczb z formularzy, brak „-0,00”, odporność progów i zakresów, czcionki PDF z `assets/`, obrazy w nietypowych trybach jako prawdziwy JPEG. |
| `test_ciag_do_pelna.py` | Ostrzeżenie „to tankowanie przerywa ciąg”: pasek pod „do pełna”, gdy wpis byłby kolejnym z rzędu bez pełnego baku, a odcinka nie zamyka późniejszy pełny. Kolejność jak w statystykach (data, potem licznik; wpis bez licznika na końcu dnia), wpis wstecz w zamkniętym odcinku milczy, w otwartym liczy też późniejsze niepełne, edytowany wpis nie stoi sam przed sobą, hybryda liczy ciąg osobno dla paliwa i prądu. Treść: liczba z odmianą, kilometry i data pełnego baku, wariant bez pełnego baku w historii, „ładowanie” przy prądzie — i że obietnica „policzy się po pełnym baku” jest prawdą. Formularz: pasek pod polem, znika po zaznaczeniu, duplikat niepełnego pokazuje go od razu. Wskaźnik baku: dolewki po pełnym baku wchodzą do stanu, nie ponad pojemność, a po przestrzelonym szacunku liczą się od pustego baku. |
| `test_jednostka_dystansu.py` | Kilometry albo mile (baza zawsze w km): całe mile wracają na ekran bez zmian, nieruszone pole formularza wraca do bazy co do kilometra (`km_przy_otwarciu`), samodzielne „km” w etykiecie zmienia się, „km/l” i „kWh/100km” nie. Progi w okrągłych milach, zapisany próg spoza listy nie znika. Spalanie w l/100km, km/l, mpg (USA) i mpg (UK), prąd w kWh/100mi i mi/kWh. Ustawienia: lista jednostek elektryka na ekranie, przełącznik km|mi podpowiada parę i wraca do poprzedniej, zapis. Edycja tankowania w milach nie przesuwa licznika. W milach żaden ekran, zakładka, porównanie ani tekst warstwy danych nie ma samotnego „km”. Pliki: eksport z nagłówkiem „(mi)”, import rozpoznaje jednostkę z nagłówka (i daje ją przełączyć), eksport w milach wraca importem z dokładnością do kilometra, raport PDF w milach. |
| `test_pamiec_metryk.py` | Pamięć metryk kokpitu (U-24): powrót na ekran główny bez zapisu po drodze nie liczy żadnej metryki, a kondycja i lista powiadomień liczą się raz na wejście, nie osobno dla kafelka, nagłówka, dzwonka i porównania. Unieważnia każdy zapis zmieniający wiersz — także wczytanie kopii zapasowej (plik podmieniony z pominięciem `polacz_baze`) i nowy dzień; NIE unieważnia pamięć interfejsu (ostatnio używane ekrany, pozycja startowa, układ kafelków, historia wyszukiwania), zapis tej samej wartości ani UPDATE bez trafienia. Znacznik rośnie dopiero po zatwierdzeniu, wynik liczony w trakcie cudzego zapisu nie trafia do pamięci, pamięć wydaje kopie, a budowa ekranu głównego niczego nie zapisuje. Każdy kafelek deklaruje swoje metryki — sam na kokpicie, w czterech scenariuszach, ma wszystko, czego potrzebuje. |
| `test_data_iso.py` | Sortowalna data obok dotychczasowej (U-25, migracja 44): `na_iso` czyta dokładnie to, co `parsuj_date` (każdy format listy, NULL zamiast daty minimalnej), a tekst RRRR-MM-DD sortuje się jak daty. Audyt AST: każdy jawny INSERT i UPDATE kolumny `data` w kodzie aplikacji pisze też `data_iso`, z tą samą liczbą wartości co kolumn. Ścieżki zapisu: edycja w pięciu formularzach i nowe wpisy, funkcje `db` (odczyt licznika, wizyta z listy, wydatek cykliczny, rozliczenie, podzespół, import CSV), rekord z chmury przy wpisaniu i zmianie, przywrócenie z chmury, kosz z migawką sprzed wersji 44, cofnięcie usunięcia. Migracja wypełnia kolumnę wstecz z każdego formatu, są indeksy (auto_id, data_iso). Eksport tnie i sortuje w SQL tak jak dawny filtr w Pythonie; zdjęcia karoserii w paszporcie i archiwum sprzedanych idą chronologicznie, a nie jak tekst DD.MM.RRRR. |
| `test_cena_za_litr.py` | Pole „cena za litr” w formularzu tankowania (M-01): dwa dowolne pola z trzech liczą trzecie (zaokrąglenie jak na dystrybutorze: litry i kwota do setnych, cena do tysięcznych), przelicza się pole ruszane najdawniej, otwarty wpis przy zmianie ceny przelicza litry, a kwota zostaje; wyczyszczone pole wyliczone wraca dopiero po wyjściu z niego, wyczyszczone wpisane gasi wyliczone; podpis pod trójką i ikona pola wyliczonego; zapis liczy brakujące pole także bez zdarzeń i wymaga dwóch z trzech. Nietypowa cena: najbliższa z cen odniesienia zamiast mediany (LPG obok benzyny, garaż obok szybkiej ładowarki), próg trzykrotny, ceny z wpisów najbliższych w czasie i tego samego źródła, bez edytowanego wpisu; pasek po wyjściu z pola, znika od razu po poprawce, otwarty wpis z literówką pokazuje go od razu, zapis prosi o potwierdzenie; kWh i „ładowaniach” u elektryka, hybryda porównuje z cenami wybranego źródła. |
| `test_odliczania.py` | Ekran „Ile zostało do…” i jego kafelek (M-04): dokument liczy pasek z roku przed terminem (termin za ponad rok — pusty pasek, po terminie — pełny i na górze), status z progu powiadomień; gwarancja od pierwszej rejestracji, bez niej od zakupu, bez żadnej (albo z datą po końcu) — bez paska; limit km gwarancji od zera, z prognozą, przekroczony, bez przebiegu wcale. Podzespół te same liczby co `oblicz_stan_interwalu` (licznik „najpierw”, drugi w podpisie), bez pierwszej wymiany poza listą, km bez średniej sortują się po terminie czasowym. Okrągły przebieg co 10 000 w jednostce z Ustawień (70 000 mi, nie przeliczone km), stan na okrągłej liczbie celuje w następną. Kolejność, sprzedane auto, słowa (dni, miesiące, lata, km z prognozą, skrót na kafelek). Ekran: karta na pozycję, nagłówek z licznikiem, podgląd bez formularzy, pusty stan z przyciskiem i bez (podgląd), szuflada i wyszukiwarka; kafelek: trzy pierwsze i „(+N)”, pusty chowa się. |
| `test_warsztaty.py` | Karta warsztatu (M-05): rejestr i nazwy z wizyt łączone po kluczu nazwy (inna pisownia to ten sam warsztat), „Warsztat” — wizyta bez wykonawcy — bez karty, pozycja wizyty nie dubluje wizyty, kolejność od ostatniej wizyty. Zapis: nowa karta (także dla nazwy znanej tylko z wizyt), zmiana nazwy przepisana na wizyty i historię; odmowy bez żadnej zmiany (nazwa zajęta, zastrzeżona, pusta), podgląd nie zapisze ani nie usunie, współautor nie przepisze cudzych wizyt, a sam kontakt zmieni. Usunięcie: nagrobek z pojazdem, wizyty zostają przy nazwie, cofnięcie z tym samym `zdalne_id` zdejmuje nagrobek. Mapy: `geo:` na Androidzie, Google Maps gdzie indziej, adres do schowka, gdy nic się nie otworzy. Ekran: przyciski tylko przy danych, sekcja „Z historii wizyt”, podgląd bez FAB-a i dodawania; wiersz warsztatu na karcie wizyty; panel z wiersza; formularz (walidacja numeru, zapowiedź zmiany nazwy, zapis); wybór warsztatu w formularzu pokazuje „Zadzwoń” i „Pokaż na mapie”. |
| `test_gwarancje.py` | Gwarancje na wykonane naprawy (M-06): stan i słowa („gwarancja jeszcze 7 miesięcy”, „albo 12 000 km”, „kończy się dziś”, „wygasła”) pełnymi miesiącami, oba limity i który skończy się pierwszy, próg przypomnienia, śmieci w bazie to brak gwarancji; duplikat przenosi okres, nie datę. Migracja 45 (historia i wizyty), kolumny w chmurze jako dopisane — także hash „między aktualizacjami” (pusty `koszt_robocizny`, bez kluczy gwarancji), rekord ze starszej wersji nie kasuje gwarancji, kosz ją przenosi. Liczy się ostatnia wymiana podzespołu, wcześniejsza ma „część wymieniona ponownie”. Dzwonek w progu (data i km), cisza po końcu, w sprzedanym i przy drzemce; kondycja bez kary; „Ile zostało do…” z paskiem i podpisem. Formularze: skróty trzymają się wymiany, ręczna data zostaje, błędy blokują zapis, mile; wizyta — wspólna z `wizyty`, wyjątek przy pozycji przeżywa zapis, okno pozycji, menu pozycji bez gwarancji przy podglądzie. Karta wpisu, karta podzespołu, Karta pojazdu (sekcja tylko z trwającymi) i paszport PDF. |
| `test_presety_importu.py` | Presety importu z innych aplikacji (M-07): rozpoznanie Fuelio, Drivvo, aCar i Simply Auto po zawartości; plik z sekcjami (separator z kolejnych linii), ZIP, końce linii z Maca. Fuelio: trzy rodzaje wpisów z jednego pliku, kategoria kosztu z numeru (Parking, Tolls, Insurance → kategorie aplikacji, nieznana → tag), Service/Maintenance i ogólna z tytułem serwisowym → wizyty, pominięte przypomnienia, przychody i szablony, kwota z ilości × ceny, mile, galony, prąd z drugiego zbiornika, flaga „Missed” w uwagach; zapis i ponowny import samych duplikatów. Drivvo: pozycje kolumn sprawdzane zawartością (inny układ → dopasowanie po nazwach), „Tak/Yes”, sekcja hiszpańska. aCar: wybór auta z pliku, liczby z USA („12,345”, „$45.67”), daty MM/DD, galony. Simply Auto: podział po „Record Type”, data z trzech kolumn, miesiące od zera. Zwykły import: kategoria z tagów, notatka, wizyty z arkusza, daty amerykańskie, separator dziesiętny całego pliku. Ekran: rozpoznanie, wszystko naraz z przełącznikami, pojazd w pliku, powrót do arkusza; wyszukiwarka po nazwie aplikacji. |
| `test_szkice.py` | Kolejka „do wpisania” (M-08): szkic z bajtów aparatu (dzisiejsza data i godzina, ścieżka względna, bez pliku pośredniego) i z galerii (data z EXIF, bez niej albo z przyszłości — dzisiejsza, zepsuty plik pominięty); kolejność od najstarszego, podsumowanie i jego unieważnienie; normalizacja rodzaju, licznika i opisu; zamknięcie zostawia zdjęcie wpisowi, usunięcie zabiera je z cofnięciem; przeniesienie do innego auta; tabela lokalna, a kosz i ścieżki ją znają (kosz oddaje szkic ze zdjęciem). Odznaka w szufladzie, dzwonek dopiero po trzech dniach najstarszego (klucz, drzemka), porównanie pojazdów bez paragonów. Kokpit: baner z odmianą („1 paragon”, „3 paragony”, „5 paragonów”), kafel i FAB. Formularze ze szkicu: tankowanie (data, zdjęcie bez kopii, licznik, dystans od licznika PONIŻEJ paragonu, opis w notatce), koszt (opis jako nazwa), wizyta (licznik, notatki) — zapis zamyka szkic i wraca do kolejki albo, gdy pusta, zwyczajnie; obcy szkic i edycja go nie biorą. Trasy i rola; ekran kolejki; aparat z podstawionym `take_picture` i panel dopisków; na komputerze wybór plików; elektryk „ładuje”. |
| `test_miesiac_w_pigulce.py` | Miesiąc w pigułce: koszty w rozbiciu i słupki dni (wizyta zbiorcza raz, sąsiedni miesiąc poza), kilometry, ulubiona stacja, największy wydatek; porównanie z poprzednim miesiącem (styczeń z grudniem poprzedniego roku) i z tym samym miesiącem rok wcześniej; miesiąc w toku z tymi samymi dniami (31 marca → 28 lutego); rok to suma swoich miesięcy; lista miesięcy z wpisami i domyślny ostatni PEŁNY. Grafika: ten sam rysownik co rok z innym zestawem liczb (podpisy dni ustępują szczytowi, fakty, kafle), żaden napis grafiki roku ani miesiąca nie wychodzi poza kadr. Ekran: dni, werdykt, porównania; strzałki po miesiącach z wpisami; słupek roku otwiera miesiąc NA roku (`/rok/2025/7`, powrót do roku), router kładzie oba ekrany w stos. |
| `test_kopie_automatyczne.py` | Automatyczna kopia zapasowa: należna po N dniach (pusta instalacja nie ma czego chronić, data z przyszłości nie wstrzymuje kopii), wyłączona tylko przypomina, ręczna gasi ostrzeżenie bez przesuwania harmonogramu, zamek na dwie kopie naraz. Archiwum takie samo jak ręczne (baza, załączniki, kosz; zdjęcia bez ponownej kompresji) i sprawdzane CRC. Rotacja do K najnowszych tylko po własnych nazwach, bez podfolderów, z resztkami `.czesc`; zepsuta baza i przekłamane archiwum nie kasują dobrych kopii. Błąd zapisu na kokpicie i w dzwonku (drzemka wspólna dla pojazdów) aż do udanej kopii. Folder z innego systemu się nie liczy, domyślny na Androidzie w Dokumentach; ustawienia `kopia_*` przeżywają wczytanie kopii. Karta w Ustawieniach (lista kopii, na górze przy problemie, wybór folderu z plikiem próbnym). Start i powrót z tła przez `main.main`, „Wczytaj” z listy. |
| `test_manifest_kopii.py` | Manifest kopii zapasowej (M-11) i podgląd przed wczytaniem. `manifest.json` w archiwum ręcznym i automatycznym: format, schemat, wpisy wg tabel, SHA-256 bazy, bilans załączników razem z koszem, data ze strefą; błąd manifestu nie zatrzymuje kopii i zostawia ślad w logu. Podgląd liczy z samej bazy: kopia z manifestem, bez niego (data z pliku), goły `.db`, stary schemat bez tabel i kolumn, pusta baza; nic się nie zmienia na dysku i nie zostaje rozpakowana baza. Nieczytelne pliki dostają powód po polsku (nie-ZIP, bez bazy, śmieć zamiast bazy, brak pliku, błąd CRC), kopia z nowszego schematu — odmowę. Zgodność z manifestem: suma SHA-256, liczba wpisów i schemat tylko jako szczegół przy złej sumie (zgodna suma nie robi fałszywego alarmu), brakujące i obcięte załączniki, uszkodzony i obcy manifest bez zielonego „zgadza się”. Okno „Wczytać tę kopię?”: zawartość, porównanie z obecną bazą, czerwone uwagi i „Wczytaj mimo to”, odmowa bez pytania, brak pliku. Trzy drogi wczytania (menu przez `main.main`, plik wybrany ręcznie, „Wczytaj” z listy w Ustawieniach) pytają, zanim cokolwiek nadpiszą. |
| `test_oferta_oc_ac.py` | Notatka „najlepsza oferta OC/AC” (migracja 47): jedno pole tekstowe pojazdu plus data ostatniej zmiany TEKSTU — nowy tekst dostaje dzisiejszą datę, ten sam (także z innymi odstępami) zachowuje starą, pusty kasuje tekst razem z datą, ponad 300 znaków jest ucinane; jedna linia na kafel i zdanie „… · zapisano 01.10.2026”. Formularz auta: pole pod polisą OC z podpisem „Zapisano …”, wchodzi do wykrywania niezapisanych zmian, nieruszone pole nie odświeża daty ani nie nadpisuje notatki zmienionej w międzyczasie (kolumny idą do UPDATE tylko po zmianie), kasowanie, nowy pojazd. Karta pojazdu: wiersz tuż pod pierwszym paskiem polisy (jeden, nie pod każdym), nie znika razem z datami polis, zachęta „Zapisz najlepszą ofertę OC/AC” tylko przy polisie, podgląd czyta bez ołówka; okienko szybkiej edycji zapisuje, wypycha do chmury i odświeża kartę w miejscu (przewijanie zostaje), ta sama treść niczego nie wypycha. „Ile zostało do…”: dopisek tylko przy OC i AC; powiadomienie niesie notatkę, ale jej zmiana nie robi z dzwonka nowego powiadomienia; panel i kafel „Termin” (jedna linia „Oferta: …”). Synchronizacja karty pojazdu: kolumny jadą jak ubezpieczyciel i składka, a hash zapamiętany przed aktualizacją (bez nowych kluczy) nie wysyła karty nad zmianą drugiej osoby (`KOLUMNY_POJAZDU_DOPISANE`), za to prawdziwa lokalna zmiana nadal wygrywa. Migracja 47 z próbki wersji 46 nie rusza danych, kosz przenosi notatkę razem z datą. |
| `test_historia_pojazdu.py` | Przycisk „Sprawdź w CEPiK” (M-14): trzy dane w kolejności formularza Historii Pojazdu — numer i VIN bez odstępów i wielkimi literami, data DD.MM.RRRR (także z zapisu ISO), nieczytelna tak, jak ją wpisano, brak jako pusty napis. Strona w zewnętrznej przeglądarce (`LaunchMode.EXTERNAL_APPLICATION`, pilnowane też na prawdziwym Flecie), bez niej adres do schowka. Komplet: jedno dotknięcie kopiuje numer, otwiera stronę i zostawia okienko z wyróżnionym VIN-em; dotknięcie wiersza kopiuje i przesuwa wyróżnienie, „Otwórz stronę” bierze następną wartość. Brak: strona się nie otwiera, myślnik bez kopiowania, „Uzupełnij” do formularza (podgląd bez niego), stronę da się otworzyć z okienka. Przycisk w Specyfikacji pod „Pierwszą rejestracją” (ta z kopiowaniem), podpowiedź o „Wstecz” tylko na Androidzie. |
| `test_historia_cen_czesci.py` | Historia cen części, sklep i link przy pozycji magazynu (M-15, migracja 48). Dziennik zakupów z formularza pozycji: nowa pozycja zapisuje zakup (data domyślnie dzisiejsza, kupiona ilość = stan, sklep w pisowni już używanej, link z dopisanym https://), ta sama data zakupu poprawia zakup, nowa dopisuje drugi, a kupiono tyle, o ile urósł stan; cena sprzed aktualizacji (bez wiersza w dzienniku) liczy się w locie i trafia do dziennika dopiero, gdy pozycja ją traci — nową datą, skasowaną ceną, usunięciem (cofnięcie nie dubluje punktu) albo scaleniem duplikatów (oba zakupy zostają, sklep i link przechodzą z duplikatu); ceny bez daty: stara „kiedyś”, bieżąca „teraz”; zmiana nazwy zabiera historię, chyba że starą nosi inna pozycja. „Kupiłem ponownie”: stan rośnie, cena = ostatni zakup (nie średnia), drugi zakup tego dnia sumuje ilość; złe dane i podgląd — odmowa. „Dopisz cenę” wymaga daty, ten sam dzień poprawia. Rachunek: zmiana od pierwszego datowanego zakupu w tej samej jednostce, najtańszy, poprzednie, odstęp słownie, podwyżki od 20% tylko dla części wciąż w magazynie i obserwacja „Części drożeją”. Link: walidacja i domena; sklepy od najczęstszego; wyszukiwarka (tekst i `sklep:`) i kolumny CSV. Ekrany: linijka „Wcześniej…” z chipem „+50% od 01.2024” i sklepem z linkiem na karcie (z audytami), menu (podgląd bez „Kupiłem ponownie”), arkusz z iskrą, najtańszym, „cena teraz” i usuwaniem z cofnięciem, okno „Kupiłem ponownie” (podpowiedź, przeliczanie, walidacja), okno „Dopisz cenę”, podpowiedź przy nazwie w formularzu. Migracja 48 z próbki 47 niczego nie przepisuje do dziennika; sklep i link jadą jako `dopisane` (pierwsza synchronizacja po aktualizacji nie wysyła magazynu), zakupy jadą do chmury i wracają z `data_iso`; kosz przenosi historię cen i sklep. |
| `test_co_nowego.py` | Ekran „Co nowego” (M-19). Lista wydań: numer wersji to data bez zer wiodących (drugie wydanie dnia `.2`), najnowsze na górze, `pyproject.toml` ma w `[project]` tylko tę samą wersję (Android pokazuje ją w informacjach o aplikacji, `name` i `dependencies` zmieniłyby build), każda pozycja ma tytuł i opis bez samotnego „km”, ikona istnieje w `ft.Icons`, a „Pokaż” prowadzi do ekranu z rejestru z trasą albo zakładką. Wersje porównywane liczbowo („2026.9.30” < „2026.10.1”). Start: telefon bez zapamiętanej wersji odgaduje ją ze schematu sprzed migracji (tabela 38–48; próg wydania to schemat, przy którym telefon ma na pewno całe wydanie), baza nieczytelna — wszystko, świeża instalacja — nic; zapamiętanej start nie rusza, oznaczenie widzianych nigdy jej nie cofa, brak klucza nie daje odznaki. Przez `main.main`: ekran otwiera się sam raz (próbka schematu 43 widzi wydania od 25 września), przebudowa nie gasi plakietek, wyłączony przełącznik zostawia kokpit, rola podglądu nie dostaje „Pokaż” przy kolejce paragonów ani imporcie. Ekran: „Nowe”, „Wcześniej…”, liczba nowości, „Pokaż” do trasy, zakładki i podzakładki (Checklisty), bez pojazdu tylko ekrany bez pojazdu, „Gotowe” tylko po aktualizacji. Odznaka w menu do otwarcia, ekran w wyszukiwarce, karta „O aplikacji” z przełącznikiem i wersja w nagłówku logu. Wczytanie kopii (wprost i z menu) zostawia `nowosci_*` tego urządzenia. |

Listy widoków ani migracji nie ma tu przepisanej ręcznie — pierwsza bierze się
z przejścia pakietu `views`, druga z odczytu AST z `db/migracje.py`. Nowy ekran
i nowa migracja są objęte testami od razu.

## Migracje: trzy niezależne sprawdzenia

Migracja, która raz poszła do ludzi, jest u nich **wykonana**. Poprawiona wstecz
nie zmienia niczego w ich bazie, a zmienia wszystko w bazie zakładanej od zera:
świeża instalacja dostaje kolumnę, zaktualizowana nie. Na własnym komputerze tego
nie widać, bo obie ścieżki przechodzą przez ten sam, zmieniony kod. Dlatego są
trzy sprawdzenia, a nie jedno.

**1. Drabinka odtworzona z kodu.** Baza w każdej z 42 wersji po `init_db()` ma
mieć dokładnie ten sam schemat, co świeża. Łapie migrację, która nie jest
powtarzalna albo psuje się przy starcie z konkretnej wersji.

**2. Zamek na odciskach** (`odciski_migracji.txt`). Skrót SHA-256 każdej wydanej
migracji. Łapie poprawianie przeszłości — czego punkt 1 z definicji nie widzi.

**3. Próbki baz** (`probki/schemat_NN.sql`). Zamrożone zrzuty SQL z danymi, po
jednym na wersję. Łapią to samo co punkt 2, ale **na danych** — i pozwalają
uruchomić najważniejszy test w projekcie komukolwiek, bez kopii prawdziwej
`flota_zadania.db` (są w niej VIN-y, numery polis i telefony; w repozytorium jej
nie ma i być nie może).

### Po dopisaniu nowej migracji

Zawsze **na końcu** drabinki, a potem:

```
python tests/test_migracje.py --zapisz
```

Polecenie **dopisuje** brakujący odcisk i brakującą próbkę. Istniejących **nie
rusza** — i to jest cała wartość obu plików. Gdyby przepisywało komplet,
wystarczyłoby poprawić starą migrację, odświeżyć wzorce i wszystko zrobiłoby się
zielone. Świadome przepisanie historii wymaga skasowania plików ręcznie, czyli
czynności, której nie da się wykonać przy okazji.

Sprawdzone: po poprawieniu migracji 1 i uruchomieniu `--zapisz` czerwonych jest
**41 testów**. Po dopisaniu migracji 41 `--zapisz` dokłada jedną linijkę i jeden
plik, reszta zostaje bit w bit.

### Skąd biorą się dane w próbkach

Zasiew jest sterowany schematem, nie listą wpisaną w kodzie: chodzi po
`PRAGMA table_info` i `PRAGMA foreign_key_list`, ustala kolejność rodzic-przed-
dzieckiem i wypełnia kolumny według nazw i typów (kolumny słownikowe dostają
prawdziwe wartości ze stałych aplikacji). Tabela dołożona jutrzejszą migracją
dostaje dane bez dopisywania czegokolwiek.

Osobno ustawiane są **punkty zaczepienia** dla pięciu migracji, które nie zmieniają
schematu, tylko uzupełniają istniejące wiersze — podzespół z „opon" w nazwie,
pojazd elektryczny, zapamiętana zakładka „2". Bez nich te bloki wykonują się na
zerze wierszy i nie dowodzą niczego.

Format to zrzut SQL, a nie plik `.db`: tekst zamiast bajtów, więc diff coś znaczy
(13 kB tekstu zamiast 344 kB binariów na wersję).

**Uczciwa uwaga:** próbki wygenerowane dzisiaj odtwarzają drabinkę taką, jaka jest
dzisiaj — nie są zapisem archeologicznym tego, co naprawdę wyszło do ludzi rok
temu. Od dziś są jednak punktem odniesienia, którego nie da się zmienić mimochodem.

## Cztery audyty

Trzy pierwsze były jednorazowymi skryptami: napisane, uruchomione raz,
wyrzucone. Każdy wykrył prawdziwy błąd, więc każdy zasługuje na to, żeby
działać przy każdej zmianie.

**Audyt `expand`** — chodzi po FAKTYCZNIE zbudowanym drzewie kontrolek i szuka
`expand` tam, gdzie szerokość jest nieograniczona: w pasku przewijanym,
w pasku zawijanym i w wierszu zagnieżdżonym w innym wierszu. Model jak
`RenderFlex`. To nie jest kosmetyka — Flutter rzuca wtedy wyjątek w czasie
działania.

**Audyt chipów** — w każdym pasku `wrap=True` sprawdza, czy któreś dziecko
rozciągnie się na całą linijkę (brak `width` i wiersz bez `tight=True`).
Pomija `items` PopupMenuButtona, bo rozwinięte menu rysuje się w osobnej
warstwie. W pasku PRZEWIJANYM ten sam kod kurczy się do treści — dlatego błąd
wychodzi dopiero po przejściu paska na zawijanie.

**Audyt pól kontrolek (AST)** — kontrolki Fleta to dataclassy bez `__slots__`,
więc `pole.czegostam = x` nigdy nie rzuca wyjątku: dokleja atrybut, którego nikt
nie czyta. Audyt porównuje przypisania i argumenty konstruktorów z
`__dataclass_fields__` zainstalowanego Fleta. Zgłasza tylko zmienne
o jednoznacznie ustalonym typie (przypisane dokładnie raz przez `ft.Coś(...)`).
Osobno sprawdza `run_task`: argument musi być prawdziwym `async def`, bo lambda
i zwykła funkcja są odrzucane i korutyna przepada bez śladu.

**Audyt cichych `except: pass` (AST)** — liczy bloki, w których jedyną
instrukcją jest `pass`, i porównuje wynik z zamrożoną listą w
`ciche_wyjatki.txt`. Nie zabrania ich: większość jest słuszna (kontrolki nie ma
jeszcze w drzewie strony, starsza wersja Fleta nie zna zdarzenia). Chodzi o to,
żeby NOWY cichy blok był decyzją, a nie odruchem — od czasu `log.py` zapisanie,
co zostało połknięte, kosztuje jedną linijkę: `log.polkniety("opis")`. Kluczem
jest plik, nie numer linii, bo numer zmienia się przy każdej edycji powyżej.

```
python tests/audyty.py            # raport, w tym rozjazd z zamkiem
python tests/audyty.py --zapisz   # odświeżenie zamku po świadomej zmianie
```

Każdy audyt ma WŁASNE testy na syntetycznych drzewkach i plikach — audyt bez
testów jest wart tyle, co jego ostatnie uruchomienie: cicho przestaje cokolwiek
znajdować i nikt tego nie zauważa, bo zielono.

Świadome wyjątki mieszkają w `audyty.py` jako `DOZWOLONE_POLA`
i `NIEROZSTRZYGNIETE_RUN_TASK` — każdy wpis to decyzja, nie przeoczenie.

## Liczby: jedno miejsce na skład

Ekran, eksport CSV, generator grafiki i raport PDF miały po własnej kopii tych
samych trzech linijek: zaokrąglenie, przecinek dziesiętny, separator tysięcy.
Zaokrąglenia akurat się zgadzały — ale zgadzały się PRZYPADKIEM, bo nic ich nie
trzymało razem.

Dziś skład robi `db.liczba_na_tekst` i tylko on. `utils.formatuj_liczba`
(ekran) i `db.formatuj_liczba_eksport` (pliki) są opakowaniami, które podejmują
jedną decyzję: co pokazać, gdy wartości NIE MA. Ekran woli zero, arkusz pustą
komórkę — różnica zamierzona i też opisana testem.

`test_formatowanie.py` porównuje obie drogi na kilkunastu tysiącach wartości
(z połówkami i ćwiartkami osobno) i dodatkowo wypisuje kilkanaście zaokrągleń
WPROST, żeby ich zmiana była widoczna w diffie, a nie tylko w wyniku porównania
dwóch funkcji ze sobą.

`audyt_recznego_formatowania` pilnuje drugiej połowy: szuka separatora tysięcy
w formacie (`:,`) i podmiany kropki na przecinek poza dwoma miejscami, którym
wolno — rdzeniem w `db/pomocnicze.py` i świadomą kopią w `log.py` (log nie
importuje niczego z projektu, więc kopii nie da się usunąć; zgodność obu pilnuje
osobny test). Idiomów PARSERA (`replace(",", ".")`) audyt nie rusza.

## Start aplikacji: co jest przed pierwszym pikselem

`init_db()` robiło przy każdym uruchomieniu cztery rzeczy: drabinkę migracji,
kasowanie odroczonych załączników, sprzątanie wygasłego kosza i (raz) naprawę
ścieżek. Tylko pierwsza jest potrzebna do narysowania ekranu; trzy pozostałe
rosną razem z danymi, bo chodzą po plikach. Zostały wyniesione do
`db.porzadki_startowe()`, które `main.py` woła w wątku w tle po pierwszym
renderze.

`test_start.py` pilnuje podziału z obu stron — że `init_db()` już tego nie robi
(inaczej przeniesienie byłoby pozorne) i że `porzadki_startowe()` robi to
naprawdę (inaczej sprzątanie przestałoby się dziać w ogóle). Osobno sprawdzana
jest jednorazowość naprawy ścieżek: chodzi po WSZYSTKICH załącznikach w bazie,
więc znacznik jest tu całą treścią.

Czas mierzy `log.zmierz()` i zapisuje do dziennika, więc profil startu jedzie
razem z „Wyślij log" — z prawdziwego telefonu i prawdziwych danych, zamiast
z komputera, na którym wszystko jest szybkie.

## Kopia z nowszej wersji aplikacji

Migracje idą tylko w przód i nigdy nie pójdą w tył. Kopia zrobiona na telefonie
z nowszą wersją aplikacji, wczytana na komputerze ze starszą, zostawiłaby bazę
z kolumnami, o których ten kod nie wie: nowe pola przestałyby się wypełniać
i nie jechałyby do chmury — a nic by się przy tym nie wywaliło.

`db.sprawdz_kopie_przed_wczytaniem()` czyta numer schematu z pliku albo wprost
z archiwum (wypakowując SAM plik bazy) i odmawia, zanim `wykonaj_import` ruszy
choćby kopię bezpieczeństwa. Plik otwierany jest w trybie **tylko do odczytu** —
sprawdzany nie ma prawa się przy tym zmienić, co pilnuje osobny test.

Blokowana jest wyłącznie kopia NOWSZA. Starsza przechodzi bez słowa, bo
dociągnięcie jej drabinką to normalna droga; nieczytelna też przechodzi, bo od
zgłaszania uszkodzonego pliku jest sam import, razem z przywróceniem bazy sprzed
próby. Numer wersji aplikacji bierze się z `len(migracje)` zapamiętanego przez
`init_db()` i jest porównywany z drabinką odczytaną z AST — dopisana migracja
przesuwa obie liczby naraz albo test robi się czerwony.

## Kształt wyników `db` — dwie połowy jednej kontroli

`pobierz_dane_timeline` urosło kiedyś z ośmiu elementów krotki do dziewięciu.
Rozpakowanie w innym pliku wywaliło się dopiero w czasie działania
(`too many values to unpack`) — u kogoś, kto akurat wszedł na ten ekran mając
dane. Publiczne funkcje `db` zwracające krotki i słowniki mają dziś adnotacje
zwrotu, ale sama adnotacja niczego nie egzekwuje: nieaktualna kłamie równie
gładko, jak kłamał komentarz w docstringu. Dlatego pilnują jej dwie rzeczy:

**`test_typy_db.py` — od strony źródła.** Woła każdą opisaną funkcję na bazie
testowej i porównuje wynik z adnotacją. Arność krotki sprawdzana twardo, typy
elementów miękko (`None` przechodzi zawsze — w SQLite prawie każda kolumna może
być NULL, więc test sprawdzałby wtedy dane, a nie kod). Krotka, która urosła,
zapala ten test w tej samej chwili.

**Audyt kształtu — od strony konsumentów.** Czyta AST i porównuje z adnotacją
każde `for a, b, c in db.f(…)`, każde `a, b = db.f()` i każdy `wiersz[i]`.
Śledzi tylko zmienne wiązane w swoim zakresie dokładnie raz — ta sama ostrożność,
co w audycie pól kontrolek, i jedyny powód, dla którego wynik nadaje się do
czytania. Nie zobaczy wiersza, który poszedł do funkcji pomocniczej albo do
metody jako argument; od tej strony pilnuje go test wykonania.

Razem zamykają obieg: krotka rośnie → czerwony test wykonania → poprawiasz
adnotację → czerwony audyt na każdym miejscu, które trzeba dostosować.

Trzeci test, `test_kazda_konsumowana_funkcja_db_ma_adnotacje`, pilnuje żeby
pokrycie nie kurczyło się po cichu: nowa funkcja, której wynik ktoś już
rozpakowuje, musi powiedzieć, jak ten wynik wygląda.

## Schemat kontra kod — dwa kierunki

`test_schemat.py` porównuje cztery listy z prawdziwym schematem, ale to nie jest
jedno sprawdzenie, tylko dwa o zupełnie różnym ciężarze.

**Lista → schemat** (kolumna z listy istnieje w bazie) jest kierunkiem tanim.
Usunięta kolumna wywala zapytanie od razu, więc i bez testu nikt tego nie
przegapi.

**Schemat → lista** (każda kolumna w bazie jest przez kod rozstrzygnięta) jest
tym, po co ten plik naprawdę powstał. Dopisujesz migracją kolumnę, zapominasz
dopisać ją do `KONFIGURACJA_SYNC` — i nic się nie dzieje. Aplikacja działa,
testy są zielone, a dane po prostu nie jadą do chmury. Wychodzi to dopiero
wtedy, gdy druga osoba pyta, czemu u niej tego nie ma.

Ten kierunek ma cztery zbiory świadomych wyjątków (`POZA_SYNC_SWIADOMIE`,
`POZA_POJAZDEM_SWIADOMIE`, `POZA_SCIEZKAMI_SWIADOMIE`, `POZA_KOSZEM_SWIADOMIE`) —
każdy wpis z powodem wpisanym obok. Pilnuje ich `test_wyjatki_nie_gnija`: wpis,
który przestał być potrzebny, jest gorszy od braku wpisu, bo wygląda jak
decyzja, a jest śmieciem po zmianie sprzed pół roku.

## Pakiet `sync/` — trzy pułapki, z których każda milczy

`sync.py` był piątym i ostatnim dużym plikiem rozbitym na moduły ułożone od
najmniej zależnych do najbardziej. Przy `db`, `utils` i dwóch pakietach widoków
najgorszym skutkiem pomyłki był nieotwierający się ekran. Tutaj jest nim
nadpisanie cudzych danych, więc zasady podziału dostały testy.

**1. `from .modul import nazwa` robi KOPIĘ wiązania.** Dopóki nazwa jest tylko
czytana albo mutowana w miejscu, kopia i oryginał to jeden obiekt. Ale nazwa
przypisywana potem przez `global` rozjeżdża się z kopią bezszelestnie —
`sync._delta_dostepna` pokazywałoby `None` w chwili, gdy `sync.delta` ma już
`False`. Dlatego `_klient_cache` i `_delta_dostepna` NIE są re-eksportowane,
a `test_nazwa_przypisywana_globalnie_nie_wychodzi_z_modulu` pyta o to
z drugiej strony niż intuicja: nie „czy ten moduł ją wystawia", tylko „czy
ktokolwiek ją wystawia albo importuje". Zamiana `lista.clear()` na `lista = []`
w module, który tę listę tylko importuje, jest właśnie takim przypadkiem.

**2. Ta sama kopia unieważnia `monkeypatch.setattr(sync, ...)`.** Blokada sieci
z `conftest.py` podmieniała `sync._upewnij_sesje` — po podziale `przywracanie`,
`przebieg` i `wspoldzielenie` mają własne wiązanie, więc podmiana samego
pakietu przestałaby cokolwiek blokować. Bez ani jednego czerwonego testu, bo
blokada, która działa, jest niema. Dziś podmiana leci po wszystkich modułach
(tak samo jak ścieżki w fixture `magazyn`), a `WEJSCIA_DO_SIECI` jest zamkiem
na listę miejsc, w których wejście do Supabase w ogóle istnieje.

**3. Nazwa zapomniana w `__all__`** znika z `import sync` i wraca jako
`AttributeError` u wołającego — czyli na ekranie, którego nikt nie otworzył
podczas przeglądu. `test_wszystko_czego_uzywa_aplikacja_jest_pod_sync`
wyszukuje w AST każdą `sync.cos` napisaną gdziekolwiek w aplikacji i sprawdza,
czy pakiet ją wystawia.

Sam przenos był mechaniczny i został udowodniony: 49 definicji porównanych
z oryginałem po `ast.dump` i po surowym tekście. Kod definicji nie zmienił się
ani o znak — zmieniło się tylko to, w którym pliku mieszka.

## Końce linii

Projekt jest na **LF** — wszędzie, u każdego, na każdym systemie. `.gitattributes`
wymusza `eol=lf`, co nadpisuje `core.autocrlf` na Windowsie, więc nie trzeba nic
ustawiać na maszynie ani o niczym pamiętać.

Powód nie jest estetyczny. Każde narzędzie zapisujące pliki — skrypty,
generator próbek baz, CI, edytory — pisze domyślnie LF. Projekt trzymany na CRLF
zmusza do konwersji przy każdym takim zapisie, a pominięcie jej pokazuje cały
plik jako zmieniony i robi diff bezużytecznym. Uwaga „pamiętaj o CRLF" wróciła
w czterech notatkach z rzędu; to był problem konfiguracyjny udający warsztatowy.

Gdyby kiedyś wrócił (świeży `clone` bez `.gitattributes`, edytor, wklejka):

```
python tests/test_konce_linii.py            # raport: które pliki i ile razy
python tests/test_konce_linii.py --napraw   # przepisanie na LF
```

Test pilnuje trzech rzeczy naraz: braku CRLF, braku samotnego CR i braku UTF-8
BOM (dokłada go Notatnik i przekierowanie `>` w PowerShellu). Czwarty test
sprawdza sam `.gitattributes` — bez niego polityka nie przetrwa `git clone`.

Sam naprawiacz też ma testy: pomija pliki binarne i katalogi z danymi
(`.venv`, `zalaczniki`, `kosz_zalaczniki`), żeby w dniu, w którym będzie
potrzebny, nie okazał się pusty albo zbyt gorliwy.

## Dodawanie testów

`conftest.py` daje trzy fixture'y:

- `magazyn` — pusty katalog danych na wyłączność testu (baza jeszcze nie istnieje),
- `baza` — to samo plus zmigrowana baza,
- `bez_sieci` — automatyczny; każda próba połączenia z Supabase to błąd testu.

`pomoce.py` ma resztę: `utworz_pojazd()` zakłada auto z wpisem w każdej tabeli
potomnej i załącznikami na dysku, `dosyp_dane()` dokłada objętość i
różnorodność (paski filtrów pokazują się dopiero, gdy jest z czego wybierać),
`zrzut_danych()` / `zrzut_schematu()` / `odciski_zalacznikow()` służą do
porównań „przed i po", `zbuduj_strone()` daje `ft.Page` bez okna,
`klasy_widokow()` / `zbuduj_widok()` / `przygotuj_scenariusz()` budują dowolny
ekran na dowolnym układzie danych.

## Czego tu jeszcze nie ma

- audyt tekstu (`Text` w wierszu bez `expand`) z notatki o poprawkach UI —
  posłużył jednorazowo do wytypowania miejsc do poprawki, nie jest regułą do
  pilnowania.
