-- Query 08: stretches of consecutive busy weeks ("gaps and islands")
--
-- Question   For each study, in which periods did the lab record at least one session every week without
--            a break for at least three weeks, and how long was each period?
-- Concepts   gaps and islands: number the rows, subtract from a counter, group by the difference
--
-- Read it like this
--   * First, one row per (study, week) that had a completed session: DISTINCT after date_trunc('week').
--   * Then the trick. Give every week a number in time order (row_number) and also the week's absolute
--     number (days since a fixed Monday, divided by 7). While the weeks are consecutive both counters grow by
--     one together, so their DIFFERENCE stays the same. When a week is missing the absolute number jumps and
--     the difference changes. All weeks with the same difference belong to the same island.
--   * GROUP BY that difference and take min/max/count: each group is one island.
--   * The same shape finds streaks of days, runs of consecutive ids, uninterrupted logins, and so on.

WITH busy AS (
    SELECT DISTINCT study_id,
           date_trunc('week', starts_at AT TIME ZONE 'America/Sao_Paulo')::date AS week_start
    FROM lab.session
    WHERE status = 'completed'
), numbered AS (
    SELECT study_id, week_start,
           (week_start - DATE '2000-01-03') / 7
             - row_number() OVER (PARTITION BY study_id ORDER BY week_start) AS island
    FROM busy
)
SELECT st.code AS study,
       min(n.week_start) AS first_week,
       max(n.week_start) AS last_week,
       count(*)          AS weeks_in_a_row
FROM numbered AS n
JOIN lab.study AS st USING (study_id)
GROUP BY st.code, n.island
HAVING count(*) >= 3
ORDER BY st.code, first_week;
