-- Правка текста абзаца на сайте: решение 'edit' (номер вида P012, в text — новый текст абзаца целиком).
ALTER TABLE pravkiapp.review_choices DROP CONSTRAINT review_choices_choice;
ALTER TABLE pravkiapp.review_choices ADD CONSTRAINT review_choices_choice
    CHECK (choice IN ('accept', 'reject', 'counter', 'reply', 'edit'));
