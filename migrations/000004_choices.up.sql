-- Решения юриста по правкам разбора (пошаговый просмотр): принять, отклонить или встречная редакция с его текстом.
-- По ним собирается ответ контрагенту в Word. Строки удаляются вместе с разбором.
CREATE TABLE pravkiapp.review_choices (
    review_id  INT NOT NULL REFERENCES pravkiapp.reviews(id) ON DELETE CASCADE,
    change_id  VARCHAR(20) NOT NULL,
    choice     VARCHAR(10) NOT NULL,
    text       TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (review_id, change_id),
    CONSTRAINT review_choices_choice CHECK (choice IN ('accept', 'reject', 'counter')),
    CONSTRAINT review_choices_text_len CHECK (char_length(text) <= 5000)
);
