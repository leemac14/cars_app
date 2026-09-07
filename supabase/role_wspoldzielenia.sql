-- =============================================================================
--  ROLE WSPÓŁDZIELENIA POJAZDU — twarde wymuszenie po stronie Supabase
-- =============================================================================
--  Wklej CAŁY plik do: Supabase -> SQL Editor -> New query -> Run.
--  Można uruchamiać wielokrotnie (wszystko jest IF NOT EXISTS / OR REPLACE).
--
--  CO TO ROBI
--  ----------
--  Aplikacja sama pilnuje ról (chowa przyciski, nic nie wysyła w trybie
--  podglądu), ale to warstwa wygody — kto zmieni plik .py, obejdzie ją w minutę.
--  Ten skrypt przenosi granicę na serwer: wyzwalacz na tabeli `zdalne_rekordy`
--  odrzuca zapis, którego rola nie przewiduje, niezależnie od tego, jaki klient
--  go przysłał.
--
--  CZEGO NIE RUSZA
--  ---------------
--  Skrypt jest wyłącznie DODAJĄCY. Nie podmienia ani nie kasuje istniejących
--  funkcji `utworz_udostepniony_pojazd`, `dolacz_do_pojazdu`,
--  `dodaj_zdalny_rekord`, `aktualizuj_zdalny_rekord` ani `usun_zdalny_rekord`,
--  nie zmienia tabeli pojazdów i nie dotyka Twoich dotychczasowych polityk RLS.
--  Jedyna zmiana w istniejącym obiekcie to nowa, opcjonalna kolumna
--  `zdalne_rekordy.zaktualizowano` (znacznik czasu do synchronizacji
--  przyrostowej) — aplikacja radzi sobie i bez niej.
--
--  ZAŁOŻENIA
--  ---------
--  - istnieje tabela `public.zdalne_rekordy` z kolumnami
--    `id`, `pojazd_id`, `tabela`, `dane` (jsonb), `usuniete` (bool);
--  - istnieje funkcja `public.dolacz_do_pojazdu(p_kod text)` zwracająca
--    kolumny `pojazd_id` i `nazwa`.
--  Jeśli u Ciebie nazywają się inaczej, popraw je w tym pliku przed wgraniem.
--
--  ROLE
--  ----
--    wlasciciel  — udostępnił pojazd; może wszystko
--    pelna       — dołączył kodem pełnym; może wszystko (zachowanie sprzed ról)
--    wspolautor  — dopisuje własne wpisy, cudzych nie zmienia ani nie kasuje
--    podglad     — wyłącznie czyta
--
--  DOMYŚLNIE każdy, kto nie ma wiersza w `role_uczestnikow`, ma rolę 'pelna'.
--  Dzięki temu wgranie tego pliku NICZEGO nie odbiera osobom, które dołączyły
--  wcześniej — ograniczenia zaczynają obowiązywać dopiero dla tych, którzy
--  wejdą kodem roli.
-- =============================================================================


-- ---------------------------------------------------------------------------
-- 1. Znacznik czasu — podstawa synchronizacji przyrostowej
-- ---------------------------------------------------------------------------
-- Bez tej kolumny aplikacja przy każdej synchronizacji ściąga komplet rekordów
-- ze wszystkich tabel. Wykrywa jej brak sama i wraca do pełnego pobierania,
-- więc to optymalizacja, a nie wymóg.
alter table public.zdalne_rekordy
  add column if not exists zaktualizowano timestamptz not null default now();

create index if not exists idx_zdalne_rekordy_zaktualizowano
  on public.zdalne_rekordy (pojazd_id, tabela, zaktualizowano);

create or replace function public.dotknij_zdalny_rekord()
returns trigger
language plpgsql
as $$
begin
  new.zaktualizowano := now();
  return new;
end;
$$;

drop trigger if exists trg_zdalne_rekordy_znacznik on public.zdalne_rekordy;
create trigger trg_zdalne_rekordy_znacznik
  before insert or update on public.zdalne_rekordy
  for each row execute function public.dotknij_zdalny_rekord();


-- ---------------------------------------------------------------------------
-- 2. Role uczestników
-- ---------------------------------------------------------------------------
create table if not exists public.role_uczestnikow (
  pojazd_id     uuid        not null,
  uzytkownik_id uuid        not null,
  rola          text        not null check (rola in ('wlasciciel','pelna','wspolautor','podglad')),
  nadano        timestamptz not null default now(),
  primary key (pojazd_id, uzytkownik_id)
);

alter table public.role_uczestnikow enable row level security;

-- Swoją rolę wolno przeczytać; nadaje ją wyłącznie funkcja poniżej
-- (SECURITY DEFINER), więc INSERT/UPDATE z klienta nie ma tu żadnej polityki
-- i jest domyślnie zabroniony.
drop policy if exists "wlasna rola do odczytu" on public.role_uczestnikow;
create policy "wlasna rola do odczytu" on public.role_uczestnikow
  for select to authenticated
  using (uzytkownik_id = auth.uid());


-- Waga roli — przy ponownym dołączaniu nie odbieramy szerszych uprawnień,
-- które ktoś już ma. Inaczej wklejenie kodu podglądu przez współwłaściciela
-- odcięłoby mu własne auto.
create or replace function public.waga_roli(p_rola text)
returns int
language sql
immutable
as $$
  select case p_rola
           when 'wlasciciel' then 4
           when 'pelna'      then 3
           when 'wspolautor' then 2
           when 'podglad'    then 1
           else 0
         end;
$$;


create or replace function public.moja_rola(p_pojazd_id uuid)
returns text
language sql
stable
security definer
set search_path = public
as $$
  select coalesce(
    (select rola from public.role_uczestnikow
      where pojazd_id = p_pojazd_id and uzytkownik_id = auth.uid()),
    'pelna'   -- brak wiersza = uczestnik sprzed wprowadzenia ról
  );
$$;

grant execute on function public.moja_rola(uuid) to authenticated;


-- ---------------------------------------------------------------------------
-- 3. Kody zaproszeń z rolą
-- ---------------------------------------------------------------------------
-- Kody ról są LOSOWE i niezależne od kodu pełnego. Gdyby były jego wariantem
-- (np. „P-A1B2C3”), posiadacz kodu podglądu odgadłby kod pełny w dwie sekundy
-- i cała rola byłaby dekoracją.
create table if not exists public.kody_dostepu (
  kod         text        primary key,
  pojazd_id   uuid        not null,
  kod_bazowy  text        not null,
  rola        text        not null check (rola in ('pelna','wspolautor','podglad')),
  aktywny     boolean     not null default true,
  utworzyl    uuid        default auth.uid(),
  utworzono   timestamptz not null default now()
);

alter table public.kody_dostepu enable row level security;
-- Żadnej polityki: tabela jest dostępna wyłącznie przez funkcje poniżej.
-- Kod zaproszenia nie ma prawa dać się wylistować.


create or replace function public.zarejestruj_kod_dostepu(
  p_pojazd_id  uuid,
  p_kod        text,
  p_kod_bazowy text,
  p_rola       text
)
returns text
language plpgsql
security definer
set search_path = public
as $$
declare
  v_sprawdzony uuid;
begin
  if p_rola not in ('pelna','wspolautor','podglad') then
    raise exception 'Nieznana rola: %', p_rola using errcode = '22023';
  end if;

  -- Dowód, że wołający naprawdę gospodarzy przy tym pojeździe: musi znać jego
  -- kod pełny. Sprawdzamy istniejącą funkcją dołączania — dla kogoś, kto już
  -- jest uczestnikiem, jest ona bezpieczna i nic nie zmienia.
  select pojazd_id into v_sprawdzony
    from public.dolacz_do_pojazdu(p_kod_bazowy)
   limit 1;

  if v_sprawdzony is null or v_sprawdzony <> p_pojazd_id then
    raise exception 'Kod bazowy nie pasuje do tego pojazdu.' using errcode = '42501';
  end if;

  if public.waga_roli(public.moja_rola(p_pojazd_id)) < public.waga_roli('pelna') then
    raise exception 'Kody zaproszen wystawia wylacznie wlasciciel pojazdu.' using errcode = '42501';
  end if;

  insert into public.kody_dostepu (kod, pojazd_id, kod_bazowy, rola)
  values (upper(trim(p_kod)), p_pojazd_id, p_kod_bazowy, p_rola)
  on conflict (kod) do update
    set pojazd_id = excluded.pojazd_id,
        kod_bazowy = excluded.kod_bazowy,
        rola = excluded.rola,
        aktywny = true;

  return upper(trim(p_kod));
end;
$$;

grant execute on function public.zarejestruj_kod_dostepu(uuid, text, text, text) to authenticated;


create or replace function public.wycofaj_kod_dostepu(p_kod text)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
  v_pojazd uuid;
begin
  select pojazd_id into v_pojazd
    from public.kody_dostepu
   where kod = upper(trim(p_kod));

  if v_pojazd is null then
    return false;
  end if;

  if public.waga_roli(public.moja_rola(v_pojazd)) < public.waga_roli('pelna') then
    raise exception 'Kody zaproszen wycofuje wylacznie wlasciciel pojazdu.' using errcode = '42501';
  end if;

  update public.kody_dostepu set aktywny = false where kod = upper(trim(p_kod));
  return true;
end;
$$;

grant execute on function public.wycofaj_kod_dostepu(text) to authenticated;


-- Dołączanie kodem roli. Gdy podany kod nie jest kodem roli, funkcja spada do
-- dotychczasowego `dolacz_do_pojazdu` i przyznaje rolę pełną — dzięki temu
-- stare kody działają dokładnie jak wcześniej.
create or replace function public.dolacz_do_pojazdu_z_rola(p_kod text)
returns table (pojazd_id uuid, nazwa text, rola text)
language plpgsql
security definer
set search_path = public
as $$
declare
  v_kod     text := upper(trim(p_kod));
  v_wpis    public.kody_dostepu%rowtype;
  v_do_uzycia text;
  v_rola    text;
  v_pojazd  uuid;
  v_nazwa   text;
  v_obecna  text;
begin
  select * into v_wpis
    from public.kody_dostepu
   where kod = v_kod and aktywny;

  if found then
    v_do_uzycia := v_wpis.kod_bazowy;
    v_rola      := v_wpis.rola;
  else
    v_do_uzycia := v_kod;
    v_rola      := 'pelna';
  end if;

  select d.pojazd_id, d.nazwa into v_pojazd, v_nazwa
    from public.dolacz_do_pojazdu(v_do_uzycia) d
   limit 1;

  if v_pojazd is null then
    return;  -- brak danych = nieprawidłowy kod; klient zamienia to na komunikat
  end if;

  -- Nie odbieramy szerszych uprawnień, które ktoś już ma przy tym pojeździe.
  select r.rola into v_obecna
    from public.role_uczestnikow r
   where r.pojazd_id = v_pojazd and r.uzytkownik_id = auth.uid();

  if v_obecna is not null and public.waga_roli(v_obecna) >= public.waga_roli(v_rola) then
    v_rola := v_obecna;
  else
    insert into public.role_uczestnikow (pojazd_id, uzytkownik_id, rola)
    values (v_pojazd, auth.uid(), v_rola)
    on conflict (pojazd_id, uzytkownik_id) do update set rola = excluded.rola;
  end if;

  pojazd_id := v_pojazd;
  nazwa     := v_nazwa;
  rola      := v_rola;
  return next;
end;
$$;

grant execute on function public.dolacz_do_pojazdu_z_rola(text) to authenticated;


-- ---------------------------------------------------------------------------
-- 4. WYMUSZENIE — wyzwalacz na zdalne_rekordy
-- ---------------------------------------------------------------------------
-- Siedzi na tabeli, a nie w funkcjach RPC, więc obowiązuje niezależnie od tego,
-- którędy zapis przyszedł: przez `dodaj_zdalny_rekord`, `aktualizuj_zdalny_rekord`,
-- `usun_zdalny_rekord`, czy wprost do tabeli. Funkcje SECURITY DEFINER też go
-- nie omijają — `auth.uid()` czyta oświadczenia z żądania, nie z roli bazy.
--
-- Autorstwo wpisu trzymamy jako `_autor_uid` w polu `dane`. Podkreślnik na
-- początku jest umowny: aplikacja pomija takie klucze przy liczeniu odcisku
-- treści (patrz sync._hash_zawartosci), więc dołożenie ich przez serwer nie
-- wywołuje fałszywych konfliktów. Nie porównujemy po `dodane_przez`, bo to
-- dowolny tekst wpisany w Ustawieniach — dwie osoby mogą mieć to samo imię
-- i każdy może wpisać cudze.
create or replace function public.pilnuj_roli_zdalnych_rekordow()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_pojazd uuid;
  v_rola   text;
  v_autor  uuid;
begin
  v_pojazd := coalesce(new.pojazd_id, old.pojazd_id);
  v_rola   := public.moja_rola(v_pojazd);

  if v_rola = 'podglad' then
    raise exception 'Ten pojazd masz w trybie tylko do odczytu.' using errcode = '42501';
  end if;

  if tg_op = 'INSERT' then
    new.dane := coalesce(new.dane, '{}'::jsonb)
                || jsonb_build_object('_autor_uid', auth.uid());
    return new;
  end if;

  v_autor := nullif(old.dane ->> '_autor_uid', '')::uuid;

  -- Współautor rusza tylko to, co sam założył — i tylko w tabelach, w których
  -- „czyj to wpis” w ogóle ma sens. Podzespoły, opony, magazyn czy warsztaty
  -- to wspólny inwentarz pojazdu; zablokowanie ich odcięłoby go od rzeczy,
  -- które sam dopisuje.
  if v_rola = 'wspolautor'
     and old.tabela in ('tankowania','wizyty','historia','inne_koszty')
     and v_autor is not null
     and v_autor <> auth.uid() then
    raise exception 'Jako wspolautor nie zmieniasz cudzych wpisow.' using errcode = '42501';
  end if;

  if tg_op = 'UPDATE' then
    -- Autor zostaje ten sam, choćby klient przysłał całą treść od nowa.
    new.dane := coalesce(new.dane, '{}'::jsonb)
                || jsonb_build_object('_autor_uid', coalesce(v_autor, auth.uid()));
    return new;
  end if;

  return old;  -- DELETE
end;
$$;

drop trigger if exists trg_role_zdalne_rekordy on public.zdalne_rekordy;
create trigger trg_role_zdalne_rekordy
  before insert or update or delete on public.zdalne_rekordy
  for each row execute function public.pilnuj_roli_zdalnych_rekordow();


-- ---------------------------------------------------------------------------
-- 5. Sprawdzenie po wgraniu
-- ---------------------------------------------------------------------------
-- Powinno zwrócić cztery funkcje i dwa wyzwalacze:
--
--   select proname from pg_proc
--    where proname in ('moja_rola','zarejestruj_kod_dostepu',
--                      'wycofaj_kod_dostepu','dolacz_do_pojazdu_z_rola');
--
--   select tgname from pg_trigger
--    where tgrelid = 'public.zdalne_rekordy'::regclass and not tgisinternal;
--
-- Cofnięcie wszystkiego (gdyby coś poszło nie tak):
--
--   drop trigger if exists trg_role_zdalne_rekordy on public.zdalne_rekordy;
--   drop trigger if exists trg_zdalne_rekordy_znacznik on public.zdalne_rekordy;
--   drop function if exists public.pilnuj_roli_zdalnych_rekordow();
--   drop function if exists public.dolacz_do_pojazdu_z_rola(text);
--   drop function if exists public.wycofaj_kod_dostepu(text);
--   drop function if exists public.zarejestruj_kod_dostepu(uuid, text, text, text);
--   drop function if exists public.moja_rola(uuid);
--   drop function if exists public.waga_roli(text);
--   drop table if exists public.kody_dostepu;
--   drop table if exists public.role_uczestnikow;
--   -- kolumnę zaktualizowano można zostawić; aplikacja jej nie wymaga
