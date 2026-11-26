-- Query 07: the three most active participants of each study
--
-- Question   Which three participants completed the most sessions in each study? (Ties are broken by code,
--            so the answer is always the same.)
-- Concepts   top-N per group: ROW_NUMBER() over a partition, versus LATERAL with LIMIT
--
-- The two variants return the same rows.
--   window    ranks everybody, then keeps ranks 1 to 3. Reads the whole table once. Simple and fast when
--             most rows are needed anyway.
--   lateral   for each study, runs a small "top 3" subquery. With an index that matches the ORDER BY it can
--             stop after three rows per group, which wins when there are many rows per group and few groups.
--   RANK() would keep all tied rows (possibly more than three); ROW_NUMBER() always keeps exactly three.

-- @variant window
SELECT study, participant, completed
FROM (
    SELECT st.code AS study, p.code AS participant, count(*) AS completed,
           row_number() OVER (PARTITION BY st.code ORDER BY count(*) DESC, p.code) AS rn
    FROM lab.session AS s
    JOIN lab.study       AS st USING (study_id)
    JOIN lab.participant AS p  USING (participant_id)
    WHERE s.status = 'completed'
    GROUP BY st.code, p.code
) AS ranked
WHERE rn <= 3
ORDER BY study, rn;

-- @variant lateral
SELECT st.code AS study, top.participant, top.completed
FROM lab.study AS st
CROSS JOIN LATERAL (
    SELECT p.code AS participant, count(*) AS completed
    FROM lab.session AS s
    JOIN lab.participant AS p USING (participant_id)
    WHERE s.study_id = st.study_id AND s.status = 'completed'
    GROUP BY p.code
    ORDER BY count(*) DESC, p.code
    LIMIT 3
) AS top
ORDER BY st.code, top.completed DESC, top.participant;
