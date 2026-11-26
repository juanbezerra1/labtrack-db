-- seed 06: statistics, the materialized view, and housekeeping.

-- (After this file the runner executes VACUUM (ANALYZE): the planner decides from statistics, which are
-- empty after a bulk load, and index-only scans need the visibility map that VACUUM builds. VACUUM cannot
-- run inside a transaction, so it is not in a .sql file.)

REFRESH MATERIALIZED VIEW lab.mv_monthly_throughput;

-- The helper schema was only needed to generate the data.
DROP SCHEMA lab_seed CASCADE;
