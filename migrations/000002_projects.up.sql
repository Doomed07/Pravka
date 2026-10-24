-- Договор как проект: разборы одного договора — его раунды. Номер раунда — порядок разборов проекта по времени.
-- По проекту видно, какие правки контрагента повторились, к каким пунктам он вернулся и что вы решили раньше.
CREATE TABLE pravkiapp.projects (
    id         SERIAL PRIMARY KEY,
    user_id    INT NOT NULL REFERENCES pravkiapp.users(id) ON DELETE CASCADE,
    name       VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT projects_name_not_empty CHECK (char_length(btrim(name)) >= 1)
);

CREATE INDEX projects_user_created_idx ON pravkiapp.projects (user_id, created_at DESC, id DESC);

ALTER TABLE pravkiapp.reviews ADD COLUMN project_id INT REFERENCES pravkiapp.projects(id) ON DELETE CASCADE;

-- прежние разборы: у каждого свой проект с именем файла контрагента без «.docx»
WITH made AS (
    INSERT INTO pravkiapp.projects (user_id, name, created_at)
    SELECT user_id, coalesce(nullif(left(btrim(regexp_replace(theirs_name, '\.docx$', '', 'i')), 255), ''), 'Договор'), created_at
    FROM pravkiapp.reviews ORDER BY id
    RETURNING id
), numbered AS (SELECT id, row_number() OVER (ORDER BY id) AS n FROM made),
   rv AS (SELECT id, row_number() OVER (ORDER BY id) AS n FROM pravkiapp.reviews)
UPDATE pravkiapp.reviews r SET project_id = numbered.id
FROM rv JOIN numbered ON numbered.n = rv.n WHERE r.id = rv.id;

ALTER TABLE pravkiapp.reviews ALTER COLUMN project_id SET NOT NULL;
CREATE INDEX reviews_project_idx ON pravkiapp.reviews (project_id, created_at, id);
