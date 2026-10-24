DROP INDEX IF EXISTS pravkiapp.projects_counterparty_idx;
ALTER TABLE pravkiapp.projects DROP COLUMN IF EXISTS dir;
ALTER TABLE pravkiapp.projects DROP COLUMN IF EXISTS counterparty_id;
DROP TABLE IF EXISTS pravkiapp.counterparties;
