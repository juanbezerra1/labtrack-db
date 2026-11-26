-- Query 02: how are the studies going?
--
-- Question   For each study: how many sessions are completed, missed or still booked, and what share of
--            the sessions that were supposed to happen actually did?
-- Concepts   GROUP BY ROLLUP, FILTER, NULLIF, integer vs numeric division
--
-- Read it like this
--   * count(*) FILTER (WHERE ...) is a count with its own WHERE: several counts in one pass, one per
--     condition, instead of one query per status. (The older spelling is sum(CASE WHEN ... THEN 1 END).)
--   * GROUP BY ROLLUP (st.code) adds a grand-total row, where st.code is NULL; coalesce() names it.
--   * 100.0 and not 100: with two integers PostgreSQL divides as integers and 7 / 9 is 0.
--   * NULLIF(x, 0) turns a zero divisor into NULL, so the result is NULL instead of an error.
--   * "Scheduled" sessions are in the future, so they are left out of the rate: they have no outcome yet.

SELECT coalesce(st.code, 'ALL STUDIES') AS study,
       count(*)                                                         AS sessions,
       count(*) FILTER (WHERE s.status = 'completed')                   AS completed,
       count(*) FILTER (WHERE s.status = 'cancelled')                   AS cancelled,
       count(*) FILTER (WHERE s.status = 'no_show')                     AS no_show,
       count(*) FILTER (WHERE s.status = 'scheduled')                   AS still_booked,
       round(100.0 * count(*) FILTER (WHERE s.status = 'completed')
             / nullif(count(*) FILTER (WHERE s.status <> 'scheduled'), 0), 1) AS completion_pct
FROM lab.session AS s
JOIN lab.study AS st USING (study_id)
GROUP BY ROLLUP (st.code)
ORDER BY st.code NULLS LAST;
