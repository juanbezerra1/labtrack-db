-- Lesson 06: sorting in memory or on disk (work_mem)
-- Needs: medium
--
-- Question  Order the feature values of the first 16,000 trials (about 300,000 values) from the largest to the
--           smallest, and then just the ten largest. (A slice of fixed size, so that the sort is the same size
--           at the medium and at the large scale.)
-- Takeaway  A sort that does not fit in work_mem (4 MB by default) is split into runs written to disk and merged
--           ("external merge"); with enough memory it is a quicksort in RAM. The plan says which happened ("Sort
--           Method"), and the sort size is in kB. Do not expect the in-memory sort to always win the clock: on a
--           fast SSD with a warm cache the two can take about the same time (look at the milliseconds in your own
--           run), and the extra I/O hurts most when many sorts compete on a busy server. What does change the
--           work is asking for less: ORDER BY ... LIMIT 10 never sorts everything, it keeps a small heap of the
--           best ten seen so far ("top-N heapsort"), in a few kilobytes. Raising work_mem for a whole server is
--           risky (every sort of every query may use that much); raise it for one session or one transaction
--           instead, as SET LOCAL does here.

-- @explain default memory
SELECT trial_id, channel_no, feature_id, value
FROM lab.trial_feature
WHERE trial_id <= 16000
ORDER BY value DESC;

-- @do
SET LOCAL work_mem = '64MB';

-- @explain more memory
SELECT trial_id, channel_no, feature_id, value
FROM lab.trial_feature
WHERE trial_id <= 16000
ORDER BY value DESC;

-- @explain only the top ten
SELECT trial_id, channel_no, feature_id, value
FROM lab.trial_feature
WHERE trial_id <= 16000
ORDER BY value DESC
LIMIT 10;

-- @expect default memory: external merge
-- @expect more memory: quicksort
-- @expect only the top ten: top-N heapsort
