-- Query 03: enrolled, but never completed a session
--
-- Question   Which enrolled participants have no completed session at all?
-- Concepts   anti-join: LEFT JOIN ... IS NULL, NOT EXISTS, NOT IN (and its NULL trap)
--
-- The three variants return the same rows; the test-suite checks that. They differ in how safe they
-- are and in how they read:
--   left_join   joins, then keeps the rows where the right side found nothing. The condition on the
--               right table (status = 'completed') MUST be in ON. Put it in WHERE and the LEFT JOIN
--               silently becomes an inner join and the query returns nothing.
--   not_exists  says what you mean ("there is no completed session"). Usually the best choice.
--   not_in      looks the simplest, but if the subquery ever returns a NULL, "x NOT IN (..., NULL)" is
--               never true and the whole query returns zero rows. Fine here (the columns are NOT NULL),
--               a time bomb when a column later becomes nullable.

-- @variant left_join
SELECT p.code AS participant, st.code AS study, e.group_label, e.enrolled_on
FROM lab.enrollment AS e
JOIN lab.participant AS p  USING (participant_id)
JOIN lab.study       AS st USING (study_id)
LEFT JOIN lab.session AS s
       ON s.study_id = e.study_id AND s.participant_id = e.participant_id AND s.status = 'completed'
WHERE s.session_id IS NULL
ORDER BY e.enrolled_on, p.code, st.code;

-- @variant not_exists
SELECT p.code AS participant, st.code AS study, e.group_label, e.enrolled_on
FROM lab.enrollment AS e
JOIN lab.participant AS p  USING (participant_id)
JOIN lab.study       AS st USING (study_id)
WHERE NOT EXISTS (
    SELECT 1 FROM lab.session AS s
    WHERE s.study_id = e.study_id AND s.participant_id = e.participant_id AND s.status = 'completed')
ORDER BY e.enrolled_on, p.code, st.code;

-- @variant not_in
SELECT p.code AS participant, st.code AS study, e.group_label, e.enrolled_on
FROM lab.enrollment AS e
JOIN lab.participant AS p  USING (participant_id)
JOIN lab.study       AS st USING (study_id)
WHERE (e.study_id, e.participant_id) NOT IN (
    SELECT s.study_id, s.participant_id FROM lab.session AS s WHERE s.status = 'completed')
ORDER BY e.enrolled_on, p.code, st.code;
