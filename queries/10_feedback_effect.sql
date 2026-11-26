-- Query 10: does the feedback lower force variability, and does it depend on the group?
--
-- Question   In FFB-01, what is the mean coefficient of variation of the force (feature force_cv) with the
--            feedback on and off, in each group, and what is the difference?
-- Concepts   conditional aggregation (a "pivot" with FILTER), joins through the long table, why you filter on
--            valid trials, rounding for stable output
--
-- Read it like this
--   * The long table has one row per (trial, channel, feature). To compare two conditions side by side
--     without a pivot function, aggregate the same column twice with different FILTERs.
--   * The condition text ends in _fb when the feedback was on (hold_40_fb) and in _nofb when it was off.
--   * WHERE t.valid: trials rejected in review still have feature values (they were computed before the review).
--     Averaging them in is a classic analysis mistake; the schema stores them on purpose and leaves the
--     filter to you.
--   * The data is synthetic and the effect is planted (see README, "What is planted in the data"): the
--     intervention group gains more from the feedback. Do not read it as a scientific result.

SELECT e.group_label,
       count(*)                                                                                  AS values_used,
       round(avg(tf.value) FILTER (WHERE right(t.condition, 3) = '_fb')::numeric, 3)             AS feedback_on,
       round(avg(tf.value) FILTER (WHERE right(t.condition, 3) <> '_fb')::numeric, 3)            AS feedback_off,
       round((avg(tf.value) FILTER (WHERE right(t.condition, 3) = '_fb')
            - avg(tf.value) FILTER (WHERE right(t.condition, 3) <> '_fb'))::numeric, 3)          AS difference
FROM lab.trial_feature AS tf
JOIN lab.trial       AS t USING (trial_id)
JOIN lab.recording   AS r USING (recording_id)
JOIN lab.session     AS s USING (session_id)
JOIN lab.enrollment  AS e ON e.study_id = s.study_id AND e.participant_id = s.participant_id
JOIN lab.study       AS st ON st.study_id = s.study_id
JOIN lab.feature_def AS f  ON f.feature_id = tf.feature_id
WHERE st.code = 'FFB-01'
  AND f.name = 'force_cv'
  AND t.valid
GROUP BY e.group_label
ORDER BY e.group_label;
