-- Единая версия договора: абзацы с правками (для страницы разбора) и docx с примечаниями.
-- У разборов, сделанных раньше, document пустой, а unified_docx — NULL: страница показывает прежний отчёт.
ALTER TABLE pravkiapp.reviews
    ADD COLUMN document     JSONB NOT NULL DEFAULT '[]',
    ADD COLUMN unified_docx BYTEA;
