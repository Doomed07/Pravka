-- Разборы договоров. Исходные docx не храним: только отчёты (в них есть выдержки из договора — это тоже
-- конфиденциальные данные, доступ — только владельцу разбора).
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

    CONSTRAINT reviews_theirs_name_not_empty CHECK (char_length(theirs_name) >= 1)
);

CREATE INDEX reviews_user_created_idx ON pravkiapp.reviews (user_id, created_at DESC, id DESC);
