-- Нормы ГК РФ для подсказок к правкам: пункты статей с полнотекстовым поиском (слова) и вектором (смысл, bge-m3).
-- Текст закона — из движка (pravki/law/gk.jsonl, источник pravo.gov.ru); веб-сервис загружает его при запуске,
-- если версия набора изменилась. Векторы считает локальная модель; без неё работает поиск по словам.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE pravkiapp.law_points (
    code      VARCHAR(20) NOT NULL,           -- «ГК РФ»
    article   VARCHAR(20) NOT NULL,           -- «506», «783.1»
    seq       INT NOT NULL,                   -- порядок пункта в статье (номера пунктов в статье иногда повторяются)
    point     VARCHAR(20) NOT NULL DEFAULT '', -- номер пункта; '' — статья без пунктов
    title     TEXT NOT NULL,
    section   TEXT NOT NULL DEFAULT '',
    chapter   TEXT NOT NULL DEFAULT '',
    paragraph TEXT NOT NULL DEFAULT '',
    edited    VARCHAR(10) NOT NULL DEFAULT '', -- последняя редакция статьи, ГГГГ-ММ-ДД
    text      TEXT NOT NULL,
    tsv       tsvector GENERATED ALWAYS AS (to_tsvector('russian'::regconfig, title || ' ' || text)) STORED,
    embedding vector(1024),

    PRIMARY KEY (code, article, seq)
);

CREATE INDEX law_points_tsv_idx ON pravkiapp.law_points USING gin (tsv);
CREATE INDEX law_points_embedding_idx ON pravkiapp.law_points USING hnsw (embedding vector_cosine_ops);

-- какая версия набора загружена и какой моделью посчитаны векторы ('' — без векторов)
CREATE TABLE pravkiapp.law_meta (
    code      VARCHAR(20) PRIMARY KEY,
    version   VARCHAR(64) NOT NULL,
    model     VARCHAR(100) NOT NULL DEFAULT '',
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
