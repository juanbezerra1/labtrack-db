-- Lesson 05: nested loop or hash join? It depends on how much you ask for
-- Needs: medium
--
-- Question  The same join, written the same way, twice: the feature values of ONE recording's trials, and the feature
--           values of ALL trials of every EMG recording.
-- Takeaway  There is no "best" join algorithm. For a handful of outer rows PostgreSQL does a nested loop: for each
--           row, one index look-up on the other table. For many rows that would be a million look-ups, so it builds
--           a hash table once and reads the other table once (hash join). The planner chooses from its row-count
--           estimates, which is why statistics (ANALYZE) matter, and why the same SQL can have different plans on
--           different amounts of data.

-- @explain few rows
SELECT count(*), avg(tf.value)
FROM lab.trial AS t
JOIN lab.trial_feature AS tf ON tf.trial_id = t.trial_id
WHERE t.recording_id = 150;

-- @explain many rows
SELECT count(*), avg(tf.value)
FROM lab.trial AS t
JOIN lab.recording AS r ON r.recording_id = t.recording_id
JOIN lab.trial_feature AS tf ON tf.trial_id = t.trial_id
WHERE r.modality = 'emg';

-- @expect few rows: Nested Loop
-- @expect many rows: Hash Join
