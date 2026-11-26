-- Lesson 04: an index for the rare rows only (partial index)
-- Needs: medium
--
-- Question  Which trials were rejected because of electrode noise? About 5 % of the trials are rejected, and
--           this is a search among them.
-- Takeaway  A normal index on reject_reason would hold an entry for every trial, 95 % of them NULL and never searched
--           for. A partial index (WHERE NOT valid) holds only the rejected ones: a fraction of the size, cheaper to
--           keep up to date, and used by every query that repeats the condition. Rule of thumb: when you always
--           look at a small, well-defined slice, index the slice.

-- @explain before
SELECT trial_id, recording_id, condition
FROM lab.trial
WHERE NOT valid AND reject_reason = 'electrode_noise';

-- @do
CREATE INDEX trial_rejected_reason_idx ON lab.trial (reject_reason) WHERE NOT valid;
CREATE INDEX trial_reason_full_idx ON lab.trial (reject_reason);

-- @explain after
SELECT trial_id, recording_id, condition
FROM lab.trial
WHERE NOT valid AND reject_reason = 'electrode_noise';

-- @show size of the two indexes
SELECT 'partial (WHERE NOT valid)' AS index, pg_size_pretty(pg_relation_size('lab.trial_rejected_reason_idx')) AS size
UNION ALL SELECT 'full', pg_size_pretty(pg_relation_size('lab.trial_reason_full_idx'));

-- @expect before: Seq Scan on trial
-- @expect after: Index Scan | Bitmap Index Scan | Bitmap Heap Scan
-- @forbid after: Seq Scan on trial
