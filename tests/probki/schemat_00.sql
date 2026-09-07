-- Próbka bazy w wersji schematu 0.
-- Plik ZAMROŻONY: zmienia się wyłącznie przez
--     python tests/test_migracje.py --zapisz
-- Ręczna edycja mija się z celem — to punkt odniesienia, nie kod.
BEGIN TRANSACTION;
CREATE TABLE ustawienia (klucz TEXT PRIMARY KEY, wartosc TEXT);
INSERT INTO "ustawienia" VALUES('ostatnia_zakladka','2');
CREATE TABLE warsztaty (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, nazwa TEXT NOT NULL, telefon TEXT, adres TEXT, notatki TEXT, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE);
CREATE TABLE wydatki_cykliczne (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, nazwa TEXT NOT NULL, kwota REAL NOT NULL DEFAULT 0.0, okres_dni INTEGER NOT NULL DEFAULT 30, nastepna_data TEXT NOT NULL, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE);
CREATE INDEX idx_warsztaty_auto ON warsztaty(auto_id);
CREATE INDEX idx_wydatki_cykliczne_auto ON wydatki_cykliczne(auto_id);
DELETE FROM "sqlite_sequence";
COMMIT;
