-- Query 05: days between visits
--
-- Question   How long does a participant wait between one completed visit and the next, in each study?
-- Concepts   window functions: LAG, PARTITION BY, ORDER BY inside OVER; timestamp arithmetic
--
-- Read it like this
--   * A window function looks at other rows without collapsing them (GROUP BY collapses). lag(starts_at)
--     OVER (PARTITION BY study_id, participant_id ORDER BY starts_at) is "the start of the previous
--     completed session of the same participant in the same study": its own little ordered list per person.
--   * The first visit has no previous one, so lag() is NULL there; the outer WHERE drops those rows.
--   * Subtracting two timestamps gives an interval; extract(epoch FROM ...) turns it into seconds.
--   * Window functions run AFTER WHERE and GROUP BY, which is why the filter on lag() needs a second
--     level (the CTE): you cannot write WHERE previous IS NOT NULL in the same SELECT that computes it.

WITH visits AS (
    SELECT study_id, participant_id, starts_at,
           lag(starts_at) OVER (PARTITION BY study_id, participant_id ORDER BY starts_at) AS previous
    FROM lab.session
    WHERE status = 'completed'
)
SELECT st.code AS study,
       count(*) AS intervals,
       round(avg(extract(epoch FROM v.starts_at - v.previous) / 86400)::numeric, 1) AS avg_days,
       round(min(extract(epoch FROM v.starts_at - v.previous) / 86400)::numeric, 1) AS min_days,
       round(max(extract(epoch FROM v.starts_at - v.previous) / 86400)::numeric, 1) AS max_days
FROM visits AS v
JOIN lab.study AS st USING (study_id)
WHERE v.previous IS NOT NULL
GROUP BY st.code
ORDER BY st.code;
