-- 0011: step 4 of 4. Check the old rows, then make the column NOT NULL.
--
-- VALIDATE CONSTRAINT scans the table, but takes only SHARE UPDATE EXCLUSIVE: reads and writes go
-- on while it runs. SET NOT NULL needs the strongest lock, but PostgreSQL 12+ skips its own scan
-- when a validated CHECK already proves the column has no NULLs, so that lock is held for an instant.

ALTER TABLE lab.session VALIDATE CONSTRAINT session_protocol_format;
ALTER TABLE lab.session ALTER COLUMN protocol_version SET NOT NULL;
ALTER TABLE lab.session ALTER COLUMN protocol_version SET DEFAULT 'v2';
