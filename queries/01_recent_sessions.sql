-- Query 01: the ten most recent completed sessions
--
-- Question   Which sessions finished most recently, and who was there?
-- Concepts   JOIN ... USING, ORDER BY ... DESC, a tie-breaker in ORDER BY, LIMIT, AT TIME ZONE
--
-- Read it like this
--   * FROM/JOIN builds one row per session with the names next to the ids. USING (study_id) is short
--     for ON s.study_id = st.study_id and also merges the two columns into one.
--   * Timestamps are stored as timestamptz (an absolute moment). The lab thinks in Sao Paulo time, so
--     the result is converted with AT TIME ZONE before it is formatted.
--   * ORDER BY starts_at alone is not deterministic: two sessions can start at the same minute in
--     different rooms. Add a column that is unique (session_id) so the same query always returns
--     the same rows in the same order. LIMIT without a total ORDER BY is a coin toss.

SELECT s.session_id,
       to_char(s.starts_at AT TIME ZONE 'America/Sao_Paulo', 'YYYY-MM-DD HH24:MI') AS starts_local,
       st.code        AS study,
       p.code         AS participant,
       s.visit_no,
       r.full_name    AS researcher,
       s.room,
       s.duration_min
FROM lab.session AS s
JOIN lab.study       AS st USING (study_id)
JOIN lab.participant AS p  USING (participant_id)
JOIN lab.researcher  AS r  USING (researcher_id)
WHERE s.status = 'completed'
ORDER BY s.starts_at DESC, s.session_id DESC
LIMIT 10;
