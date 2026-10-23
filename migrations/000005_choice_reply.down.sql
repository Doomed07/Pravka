DELETE FROM pravkiapp.review_choices WHERE choice = 'reply';
ALTER TABLE pravkiapp.review_choices DROP CONSTRAINT review_choices_choice;
ALTER TABLE pravkiapp.review_choices
    ADD CONSTRAINT review_choices_choice CHECK (choice IN ('accept', 'reject', 'counter'));
