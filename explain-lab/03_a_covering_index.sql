-- Lesson 03: an index that holds the answer (index-only scan)
-- Needs: medium
--
-- Question  What are the RMS values of the trials 1000 to 1100?
-- Takeaway  With the primary key (trial_id, channel_no, feature_id) PostgreSQL finds the rows in the index but must
--           visit the table for every one of them to read "value". If an index also CARRIES the value (INCLUDE),
--           the answer is in the index itself and the table is not touched: an Index Only Scan with zero heap
--           fetches. That works only on pages the visibility map marks as all-visible, which VACUUM maintains
--           (the seed ends with one). The price: a bigger index, and slower writes.

-- @explain before
SELECT trial_id, channel_no, value
FROM lab.trial_feature
WHERE trial_id BETWEEN 1000 AND 1100 AND feature_id = 1;

-- @do
CREATE INDEX trial_feature_covering_idx ON lab.trial_feature (trial_id, feature_id) INCLUDE (channel_no, value);

-- @explain after
SELECT trial_id, channel_no, value
FROM lab.trial_feature
WHERE trial_id BETWEEN 1000 AND 1100 AND feature_id = 1;

-- @expect before: Index Scan using trial_feature_pkey | Bitmap Heap Scan
-- @expect after: Index Only Scan using trial_feature_covering_idx
