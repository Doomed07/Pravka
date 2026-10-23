-- «Что говорит ГК»: к правке разбора — ближайшие по смыслу пункты ГК РФ в частях кодекса для этого типа договора.
-- Вектор правки считается при первом открытии разбора и хранится здесь (удаляется вместе с разбором).
CREATE TABLE pravkiapp.review_vectors (
    review_id INT NOT NULL REFERENCES pravkiapp.reviews(id) ON DELETE CASCADE,
    change_id VARCHAR(20) NOT NULL,
    model     VARCHAR(100) NOT NULL,
    embedding vector(1024) NOT NULL,

    PRIMARY KEY (review_id, change_id)
);

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
