-- Схема веб-сервиса «Правки»: пользователи и сессии, разборы договоров с решениями юриста, нормы ГК РФ и векторы
-- (bge-m3) для подсказок «Как решали раньше», «Ваши прошлые формулировки» и «Что говорит ГК».
CREATE SCHEMA pravkiapp;

-- векторы для поиска по смыслу (pgvector); нужен образ PostgreSQL с этим расширением
CREATE EXTENSION IF NOT EXISTS vector;

-- ---------- пользователи ----------

CREATE TABLE pravkiapp.users (
    id              SERIAL PRIMARY KEY,
    version         BIGINT NOT NULL DEFAULT 1,
    username        VARCHAR(30) NOT NULL,
    password_hash   TEXT NOT NULL,
    email           VARCHAR(254) NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT users_username_format CHECK (username ~ '^[A-Za-z0-9_]{3,30}$'),
    CONSTRAINT users_password_hash_len CHECK (length(password_hash) = 60),
    CONSTRAINT users_email_lowercase CHECK (email = lower(email)),
    CONSTRAINT users_email_format CHECK (email ~ '^[a-z0-9._+-]+@([a-z0-9-]+\.)+[a-z]{2,}$')
);

CREATE UNIQUE INDEX users_username_lower_uidx ON pravkiapp.users (lower(username));

CREATE TABLE pravkiapp.sessions (
    token_hash BYTEA PRIMARY KEY CHECK (octet_length(token_hash) = 32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    CHECK (expires_at > created_at),

    user_id    INT NOT NULL REFERENCES pravkiapp.users(id) ON DELETE CASCADE
);

CREATE INDEX sessions_user_id_idx    ON pravkiapp.sessions (user_id);
CREATE INDEX sessions_expires_at_idx ON pravkiapp.sessions (expires_at);

-- ---------- разборы ----------

-- Разборы договоров. Исходные docx не храним: только отчёты (в них есть выдержки из договора — это тоже
-- конфиденциальные данные, доступ — только владельцу разбора).
-- document — единая версия договора: абзацы с правками (для страницы разбора), unified_docx — она же в Word
-- с примечаниями. contract_type — тип договора (supply, services): «как решали раньше» ищется только среди
-- договоров того же типа и той же нашей роли. indexed_at — векторы абзацев и правок посчитаны (NULL — ещё нет).
CREATE TABLE pravkiapp.reviews (
    id            SERIAL PRIMARY KEY,
    user_id       INT NOT NULL REFERENCES pravkiapp.users(id) ON DELETE CASCADE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    theirs_name   VARCHAR(255) NOT NULL,
    base_name     VARCHAR(255) NOT NULL DEFAULT '',
    playbook      VARCHAR(255) NOT NULL DEFAULT '',
    playbook_name VARCHAR(500) NOT NULL DEFAULT '',
    our_role      VARCHAR(100) NOT NULL DEFAULT '',
    side          TEXT NOT NULL DEFAULT '',
    counts        JSONB NOT NULL DEFAULT '{}',
    warnings      JSONB NOT NULL DEFAULT '[]',

    report_html   TEXT NOT NULL,
    report_xlsx   BYTEA NOT NULL,
    changes       JSONB NOT NULL DEFAULT '[]',
    document      JSONB NOT NULL DEFAULT '[]',
    unified_docx  BYTEA,
    contract_type VARCHAR(50) NOT NULL DEFAULT '',
    indexed_at    TIMESTAMPTZ,

    CONSTRAINT reviews_theirs_name_not_empty CHECK (char_length(theirs_name) >= 1)
);

CREATE INDEX reviews_user_created_idx ON pravkiapp.reviews (user_id, created_at DESC, id DESC);
CREATE INDEX reviews_user_type_idx ON pravkiapp.reviews (user_id, contract_type, our_role);

-- Решения юриста по правкам разбора (пошаговый просмотр): принять, отклонить, встречная редакция с его текстом или
-- ответ на комментарий контрагента (reply). По ним собирается ответ контрагенту в Word. Строки удаляются вместе
-- с разбором.
CREATE TABLE pravkiapp.review_choices (
    review_id  INT NOT NULL REFERENCES pravkiapp.reviews(id) ON DELETE CASCADE,
    change_id  VARCHAR(20) NOT NULL,
    choice     VARCHAR(10) NOT NULL,
    text       TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (review_id, change_id),
    CONSTRAINT review_choices_text_len CHECK (char_length(text) <= 5000),
    CONSTRAINT review_choices_choice CHECK (choice IN ('accept', 'reject', 'counter', 'reply'))
);

-- Вектор правки (для «Что говорит ГК» и «как решали раньше» по смыслу). Удаляется вместе с разбором.
CREATE TABLE pravkiapp.review_vectors (
    review_id INT NOT NULL REFERENCES pravkiapp.reviews(id) ON DELETE CASCADE,
    change_id VARCHAR(20) NOT NULL,
    model     VARCHAR(100) NOT NULL,
    embedding vector(1024) NOT NULL,

    PRIMARY KEY (review_id, change_id)
);

-- Абзацы нашей редакции из разборов с векторами («Ваши прошлые формулировки»). Индекс по вектору не нужен:
-- поиск идёт только по разборам одного юриста, точный перебор быстрее и не теряет результаты из-за фильтров.
CREATE TABLE pravkiapp.review_paragraphs (
    review_id INT NOT NULL REFERENCES pravkiapp.reviews(id) ON DELETE CASCADE,
    idx       INT NOT NULL,                     -- номер абзаца в файле контрагента; < 0 — абзац удалён контрагентом
    clause    VARCHAR(50) NOT NULL DEFAULT '',
    text      TEXT NOT NULL,                    -- абзац в нашей редакции
    model     VARCHAR(100) NOT NULL,
    embedding vector(1024) NOT NULL,

    PRIMARY KEY (review_id, idx)
);

-- ---------- нормы ГК РФ ----------

-- Пункты статей с полнотекстовым поиском (слова) и вектором (смысл, bge-m3). Текст закона — из движка
-- (pravki/law/gk.jsonl, источник pravo.gov.ru); веб-сервис загружает его при запуске, если версия набора изменилась.
-- Векторы считает локальная модель; без неё работает поиск по словам.
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

-- ---------- функции для поиска похожих правок ----------

-- основы слов текста (словарь PostgreSQL 'russian'): «сроки оплаты 10 дней» → {10, дне, оплат, срок}
CREATE FUNCTION pravkiapp.lexemes(t text) RETURNS text[]
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    RETURN tsvector_to_array(to_tsvector('russian'::regconfig, coalesce(t, '')));

-- доля общих основ слов (коэффициент Жаккара): 0 — ничего общего, 1 — те же слова
CREATE FUNCTION pravkiapp.overlap(a text[], b text[]) RETURNS float8
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    RETURN CASE WHEN cardinality(a) = 0 OR cardinality(b) = 0 THEN 0
        ELSE (SELECT count(*) FROM (SELECT unnest(a) INTERSECT SELECT unnest(b)) i)::float8
           / (SELECT count(*) FROM (SELECT unnest(a) UNION SELECT unnest(b)) u) END;

-- суть правки: какие основы слов убраны (-) и какие добавлены (+). Не зависит от того, как правка записана:
-- «30 → 10» и «30 календарных дней → 10 календарных дней» дают одно и то же {+10, -30}
CREATE FUNCTION pravkiapp.edit_sig(b text, a text) RETURNS text[]
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    RETURN ARRAY(SELECT s FROM (
        SELECT '-' || x AS s FROM unnest(pravkiapp.lexemes(b)) x WHERE x <> ALL (pravkiapp.lexemes(a))
        UNION
        SELECT '+' || x FROM unnest(pravkiapp.lexemes(a)) x WHERE x <> ALL (pravkiapp.lexemes(b))) d ORDER BY s);

-- номер статьи без дробной части: «783.1» → 783
CREATE FUNCTION pravkiapp.article_no(a text) RETURNS int
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    RETURN split_part(a, '.', 1)::int;

-- какие части ГК подсказывать для типа договора: общие положения (ст. 1–16.1: осуществление прав, убытки),
-- сделки, сроки и исковая давность (ст. 153–208), обязательства и договор (ст. 307–453) — для всех;
-- поставка — купля-продажа (общие положения, ст. 454–491) и поставка (ст. 506–524);
-- услуги — возмездное оказание услуг (ст. 779–783.1) и общие положения о подряде (ст. 702–729, применяются по ст. 783)
CREATE FUNCTION pravkiapp.in_law_scope(contract_type text, article text) RETURNS boolean
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    RETURN pravkiapp.article_no(article) BETWEEN 1 AND 16
        OR pravkiapp.article_no(article) BETWEEN 153 AND 208
        OR pravkiapp.article_no(article) BETWEEN 307 AND 453
        OR (contract_type = 'supply' AND (pravkiapp.article_no(article) BETWEEN 454 AND 491
                                          OR pravkiapp.article_no(article) BETWEEN 506 AND 524))
        OR (contract_type = 'services' AND (pravkiapp.article_no(article) BETWEEN 779 AND 783
                                            OR pravkiapp.article_no(article) BETWEEN 702 AND 729));

-- обязанная сторона пункта: первая роль в именительном падеже («Заказчик уплачивает Исполнителю…» → Заказчик).
-- По смыслу модель не отличает неустойку Заказчика от неустойки Исполнителя: прошлые решения сравниваются только
-- при той же обязанной стороне (или когда сторона не названа)
CREATE FUNCTION pravkiapp.obligor(t text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    RETURN substring(coalesce(t, '') FROM
        '(?:^|[^А-Яа-яЁё])(Заказчик|Исполнитель|Поставщик|Покупатель|Арендатор|Арендодатель|Подрядчик)(?![А-Яа-яЁё])');

CREATE FUNCTION pravkiapp.same_obligor(a text, b text) RETURNS boolean
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    RETURN pravkiapp.obligor(a) IS NULL OR pravkiapp.obligor(b) IS NULL OR pravkiapp.obligor(a) = pravkiapp.obligor(b);
