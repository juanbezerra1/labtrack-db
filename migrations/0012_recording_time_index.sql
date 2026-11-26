-- labtrack: no-transaction
-- 0012: an index on a table that is being used. CREATE INDEX takes a lock that blocks writes for the
-- whole build; CREATE INDEX CONCURRENTLY builds it without that lock (slower, and it cannot run
-- inside a transaction, hence the marker on the first line: the migration runner then runs this file
-- as a single statement outside a transaction block).

CREATE INDEX CONCURRENTLY recording_recorded_at_idx ON lab.recording (recorded_at);
