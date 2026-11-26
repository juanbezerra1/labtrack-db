-- 0008: promote a value that lives inside JSON to a real column, the safe way (step 1 of 4).
--
-- The protocol version used to be written in lab.session.notes ->> 'protocol'. It is queried all
-- the time and should be checkable, so it becomes a column. On a table with data and users you do
-- it in small steps, each one safe on its own, instead of one big ALTER:
--   0008  add the column as NULLable (instant: PostgreSQL only records it in the catalog),
--   0009  fill it in from the JSON,
--   0010  add the rule as a CHECK ... NOT VALID (instant: only new and changed rows are checked),
--   0011  validate the rule (a long scan, but under a lock that lets everyone keep working) and
--         only then say NOT NULL (instant, because the validated CHECK already proves it).
-- Why four files and not one? Every migration runs in a single transaction, and a lock taken inside
-- a transaction is held until the end of it. ADD CONSTRAINT takes a strong lock; if the long
-- validation ran in the same transaction, that strong lock would be held for the whole scan.

ALTER TABLE lab.session ADD COLUMN protocol_version text;
COMMENT ON COLUMN lab.session.protocol_version IS 'Protocol version used in the session, such as v2. Was notes->>''protocol'' before migration 0008.';
