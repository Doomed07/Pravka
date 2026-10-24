-- Контрагент: верхний уровень «контрагент → договоры → раунды». Договор (проект) принадлежит контрагенту.
-- dir — папка на диске (data/contracts/...): у контрагента — имя папки, у договора — путь «Контрагент/Договор» от корня.
-- Путь договора пишется при создании и не меняется при переименовании: файлы уже лежат там.
CREATE TABLE pravkiapp.counterparties (
    id         SERIAL PRIMARY KEY,
    user_id    INT NOT NULL REFERENCES pravkiapp.users(id) ON DELETE CASCADE,
    name       VARCHAR(255) NOT NULL,
    inn        VARCHAR(12) NOT NULL DEFAULT '',
    dir        TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT counterparties_name_not_empty CHECK (char_length(btrim(name)) >= 1)
);

CREATE UNIQUE INDEX counterparties_user_name_idx ON pravkiapp.counterparties (user_id, lower(name));

ALTER TABLE pravkiapp.projects ADD COLUMN counterparty_id INT REFERENCES pravkiapp.counterparties(id) ON DELETE CASCADE;
ALTER TABLE pravkiapp.projects ADD COLUMN dir TEXT NOT NULL DEFAULT '';

-- прежние договоры: у каждого пользователя один контрагент «Без контрагента» (переименовывается на сайте), папок на диске нет
INSERT INTO pravkiapp.counterparties (user_id, name)
SELECT DISTINCT user_id, 'Без контрагента' FROM pravkiapp.projects;

UPDATE pravkiapp.projects p SET counterparty_id = c.id
FROM pravkiapp.counterparties c WHERE c.user_id = p.user_id AND c.name = 'Без контрагента';

ALTER TABLE pravkiapp.projects ALTER COLUMN counterparty_id SET NOT NULL;
CREATE INDEX projects_counterparty_idx ON pravkiapp.projects (counterparty_id, created_at DESC, id DESC);
