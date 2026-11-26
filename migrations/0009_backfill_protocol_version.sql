-- 0009: step 2 of 4. Fill the new column from the JSON; sessions without a note were run on v1.
--
-- One UPDATE is fine at this size. On a table with hundreds of millions of rows you would run it in
-- batches from a script (WHERE session_id BETWEEN ... AND ...) so that no transaction holds locks
-- for long, and this file would only record that the backfill happened.

UPDATE lab.session
SET protocol_version = coalesce(notes ->> 'protocol', 'v1')
WHERE protocol_version IS NULL;
