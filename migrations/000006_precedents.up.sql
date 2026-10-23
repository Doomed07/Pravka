-- «Как решали раньше»: к правке нового разбора — похожие правки из прошлых разборов того же юриста и решения по ним.
-- Ищем только среди договоров того же типа (поставка, услуги) и той же нашей роли: решение Поставщика Покупателю не
-- подсказка. Похожесть — доля общих слов (основы слов по словарю PostgreSQL 'russian'), без внешних моделей.
ALTER TABLE pravkiapp.reviews ADD COLUMN contract_type VARCHAR(50) NOT NULL DEFAULT '';

-- прежние разборы: тип по имени файла плейбука (supply_…, services_…)
UPDATE pravkiapp.reviews SET contract_type = CASE
    WHEN playbook ~ '(^|/)supply' THEN 'supply'
    WHEN playbook ~ '(^|/)services' THEN 'services'
    ELSE '' END;

CREATE INDEX reviews_user_type_idx ON pravkiapp.reviews (user_id, contract_type, our_role);

-- основы слов текста: «сроки оплаты 10 дней» → {10, дне, оплат, срок}
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
