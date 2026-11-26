-- Lesson 01: an index for a selective filter
-- Needs: medium
--
-- Question  Which force-variability values (force_cv) above 5.3 % are there? About 3 rows in every 10,000
--           of the table qualify.
-- Takeaway  The primary key of lab.trial_feature is (trial_id, channel_no, feature_id). A B-tree can only be
--           searched from its FIRST column, and this query does not mention trial_id, so the key is useless
--           here and PostgreSQL reads the whole table (Seq Scan). An index that starts with the columns of
--           the filter turns it into a short look-up.

-- @explain before
SELECT trial_id, channel_no, value
FROM lab.trial_feature
WHERE feature_id = 17 AND value > 5.3;

-- @do
CREATE INDEX trial_feature_feature_value_idx ON lab.trial_feature (feature_id, value);

-- @explain after
SELECT trial_id, channel_no, value
FROM lab.trial_feature
WHERE feature_id = 17 AND value > 5.3;

-- @show index sizes
SELECT 'table' AS what, pg_size_pretty(pg_relation_size('lab.trial_feature')) AS size
UNION ALL SELECT 'primary key', pg_size_pretty(pg_relation_size('lab.trial_feature_pkey'))
UNION ALL SELECT 'the new index', pg_size_pretty(pg_relation_size('lab.trial_feature_feature_value_idx'));

-- @expect before: Seq Scan on trial_feature
-- @expect after: Index Scan | Bitmap Index Scan | Index Only Scan
-- @forbid after: Seq Scan on trial_feature
