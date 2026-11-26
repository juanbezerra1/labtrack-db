-- Query 06: recorded hours, month by month, with a running total
--
-- Question   For the first half of 2025: how many hours did each study record per month, how many in total
--            so far, and what share of the study's hours (in this period) is each month?
-- Concepts   SUM() OVER with ORDER BY (running total), SUM() OVER without it (the whole partition), the
--            materialized view as a source
--
-- Read it like this
--   * sum(x) OVER (PARTITION BY study ORDER BY month) adds up from the first month to the current one:
--     the default frame when there is an ORDER BY. Drop the ORDER BY and you get the partition's total on
--     every row, which is exactly what the percentage needs as a denominator.
--   * The source is lab.mv_monthly_throughput, a materialized view: it was computed once and stored, so
--     this query reads a few dozen rows instead of re-aggregating every recording. The price is that it
--     is only as fresh as the last REFRESH MATERIALIZED VIEW.

SELECT study_code,
       month,
       hours_recorded,
       round(sum(hours_recorded) OVER (PARTITION BY study_code ORDER BY month), 2)           AS cumulative_hours,
       round(100 * hours_recorded / nullif(sum(hours_recorded) OVER (PARTITION BY study_code), 0), 1) AS pct_of_period
FROM lab.mv_monthly_throughput
WHERE month >= DATE '2025-01-01' AND month < DATE '2025-07-01'
ORDER BY study_code, month;
