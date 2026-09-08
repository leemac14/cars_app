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
| `test_sync_pakiet.py` | Pakiet `sync/`: zależności tylko w dół, `__init__.py` bez logiki, nazwy przypisywane przez `global` nie wychodzą z modułu, blokada sieci sięga każdego wiązania, aplikacja nie woła nazwy, której pakiet nie wystawia. |
| `test_log.py` | Rotujący log błędów: co łapie (połknięty wyjątek, wątek, porzucona korutyna asyncio, cudze ostrzeżenia), czego nie łapie (cudze INFO), rotacja, raport do wysłania i to, że brak miejsca na log nie wywala aplikacji. |

Listy widoków ani migracji nie ma tu przepisanej ręcznie — pierwsza bierze się
z przejścia pakietu `views`, druga z odczytu AST z `db/migracje.py`. Nowy ekran
i nowa migracja są objęte testami od razu.

## Migracje: trzy niezależne sprawdzenia

Migracja, która raz poszła do ludzi, jest u nich **wykonana**. Poprawiona wstecz
nie zmienia niczego w ich bazie, a zmienia wszystko w bazie zakładanej od zera:
świeża instalacja dostaje kolumnę, zaktualizowana nie. Na własnym komputerze tego
nie widać, bo obie ścieżki przechodzą przez ten sam, zmieniony kod. Dlatego są
trzy sprawdzenia, a nie jedno.

**1. Drabinka odtworzona z kodu.** Baza w każdej z 41 wersji po `init_db()` ma
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
