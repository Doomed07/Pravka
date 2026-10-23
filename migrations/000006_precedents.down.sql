DROP FUNCTION pravkiapp.edit_sig(text, text);
DROP FUNCTION pravkiapp.overlap(text[], text[]);
DROP FUNCTION pravkiapp.lexemes(text);
DROP INDEX pravkiapp.reviews_user_type_idx;
ALTER TABLE pravkiapp.reviews DROP COLUMN contract_type;
