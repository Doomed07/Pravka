-- Ответ юриста на комментарий контрагента (reply): попадает в ответ Word в ту же ветку примечаний.
ALTER TABLE pravkiapp.review_choices DROP CONSTRAINT review_choices_choice;
ALTER TABLE pravkiapp.review_choices
    ADD CONSTRAINT review_choices_choice CHECK (choice IN ('accept', 'reject', 'counter', 'reply'));
