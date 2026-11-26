-- Lesson 02: a function around the column hides the index
-- Needs: medium
--
-- Question  Which recordings were made on 2025-06-02? lab.recording has an index on recorded_at.
-- Takeaway  "recorded_at::date = ..." applies a function to every row's column, so the planner cannot use an
--           index on the column itself and reads everything. Ask the same thing as a RANGE on the bare
--           column and the index works. (A conversion of a timestamptz to a date also depends on the session's
--           time zone, which is why it cannot even be indexed as an expression. Another reason to prefer
--           the range, which also states the time zone explicitly.)

-- @explain function
SELECT recording_id, modality, recorded_at
FROM lab.recording
WHERE recorded_at::date = DATE '2025-06-02';

-- @explain range
SELECT recording_id, modality, recorded_at
FROM lab.recording
WHERE recorded_at >= TIMESTAMPTZ '2025-06-02 00:00-03'
  AND recorded_at <  TIMESTAMPTZ '2025-06-03 00:00-03';

-- @expect function: Seq Scan on recording
-- @forbid function: recording_recorded_at_idx
-- @expect range: recording_recorded_at_idx
-- @forbid range: Seq Scan on recording
