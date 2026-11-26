-- 0005: views. A view is a saved SELECT: it hides a join, names a business concept and costs nothing
-- to store. The materialized view at the end DOES store its rows, and must be refreshed.

-- One row per session, with the names of everything it points to.
CREATE VIEW lab.v_session_detail AS
SELECT s.session_id,
       st.code        AS study_code,
       p.code         AS participant_code,
       e.group_label,
       s.visit_no,
       r.full_name    AS researcher,
       s.room,
       s.starts_at,
       s.ends_at,
       s.duration_min,
       s.status
FROM lab.session AS s
JOIN lab.study       AS st USING (study_id)
JOIN lab.participant AS p  USING (participant_id)
JOIN lab.enrollment  AS e  USING (study_id, participant_id)
JOIN lab.researcher  AS r  USING (researcher_id);

COMMENT ON VIEW lab.v_session_detail IS 'One row per session with the names of its study, participant, group and researcher.';

-- Is each device calibrated TODAY (lab.reference_date())? The LATERAL subquery is the classic
-- "latest row per group": for every device, look at its calibrations newest first and keep one.
CREATE VIEW lab.v_device_status AS
SELECT d.device_id,
       d.kind,
       d.model,
       d.serial_no,
       d.home_room,
       c.performed_on AS last_passed_on,
       c.valid_until,
       CASE
           WHEN d.retired_on IS NOT NULL AND d.retired_on <= lab.reference_date() THEN 'retired'
           WHEN c.valid_until IS NULL                                            THEN 'never_calibrated'
           WHEN c.valid_until <= lab.reference_date()                            THEN 'overdue'
           WHEN c.valid_until <= lab.reference_date() + 14                       THEN 'due_soon'
           ELSE 'ok'
       END AS calibration_status,
       greatest(lab.reference_date() - c.valid_until, 0) AS days_overdue
FROM lab.device AS d
LEFT JOIN LATERAL (
    SELECT cal.performed_on, cal.valid_until
    FROM lab.calibration AS cal
    WHERE cal.device_id = d.device_id AND cal.passed
    ORDER BY cal.performed_on DESC
    LIMIT 1
) AS c ON true;

COMMENT ON VIEW lab.v_device_status IS
    'One row per device: calibration_status is retired, never_calibrated, overdue, due_soon (within 14 days) or ok, as of lab.reference_date().';

-- Each recording with how many of its trials survived quality control.
CREATE VIEW lab.v_recording_summary AS
SELECT rec.recording_id,
       rec.session_id,
       rec.modality,
       rec.recorded_at,
       rec.duration_s,
       rec.qc,
       count(t.trial_id)                                                AS n_trials,
       count(*) FILTER (WHERE t.valid)                                  AS n_valid_trials,
       round(100.0 * count(*) FILTER (WHERE t.valid)
             / nullif(count(t.trial_id), 0), 1)                         AS valid_pct
FROM lab.recording AS rec
LEFT JOIN lab.trial AS t USING (recording_id)
GROUP BY rec.recording_id;        -- the primary key makes the other recording columns legal here

COMMENT ON VIEW lab.v_recording_summary IS 'One row per recording with its number of trials, how many are valid, and the percentage.';

-- Where is each participant in the protocol?
CREATE VIEW lab.v_participant_progress AS
SELECT e.study_id,
       st.code                 AS study_code,
       e.participant_id,
       p.code                  AS participant_code,
       e.group_label,
       e.enrolled_on,
       st.planned_visits,
       count(s.session_id) FILTER (WHERE s.status = 'completed')                AS completed_visits,
       count(s.session_id) FILTER (WHERE s.status = 'scheduled')                AS scheduled_visits,
       count(s.session_id) FILTER (WHERE s.status IN ('cancelled', 'no_show'))  AS missed_visits,
       max(s.starts_at)    FILTER (WHERE s.status = 'completed')                AS last_completed_at,
       CASE
           WHEN p.withdrawn_on IS NOT NULL                                              THEN 'withdrawn'
           WHEN count(s.session_id) FILTER (WHERE s.status = 'completed') >= st.planned_visits THEN 'finished'
           WHEN count(s.session_id) FILTER (WHERE s.status = 'completed') = 0           THEN 'not_started'
           ELSE 'in_progress'
       END AS progress
FROM lab.enrollment AS e
JOIN lab.study       AS st USING (study_id)
JOIN lab.participant AS p  USING (participant_id)
LEFT JOIN lab.session AS s ON s.study_id = e.study_id AND s.participant_id = e.participant_id
GROUP BY e.study_id, e.participant_id, st.code, st.planned_visits, p.code, p.withdrawn_on,
         e.group_label, e.enrolled_on;

COMMENT ON VIEW lab.v_participant_progress IS
    'One row per enrollment: visits completed, scheduled and missed, and a progress label (not_started, in_progress, finished, withdrawn).';

-- Monthly throughput per study. Materialized: computed once, stored, refreshed on demand with
--   REFRESH MATERIALIZED VIEW CONCURRENTLY lab.mv_monthly_throughput;
-- (CONCURRENTLY needs the unique index below and does not block readers.)
CREATE MATERIALIZED VIEW lab.mv_monthly_throughput AS
SELECT date_trunc('month', s.starts_at AT TIME ZONE 'America/Sao_Paulo')::date AS month,
       st.code                                                                 AS study_code,
       count(*) FILTER (WHERE s.status = 'completed')                          AS sessions_completed,
       count(*) FILTER (WHERE s.status IN ('cancelled', 'no_show'))            AS sessions_missed,
       coalesce(sum(rc.n_recordings), 0)::integer                              AS recordings,
       round(coalesce(sum(rc.hours), 0)::numeric, 2)                           AS hours_recorded
FROM lab.session AS s
JOIN lab.study   AS st USING (study_id)
LEFT JOIN (
    SELECT session_id, count(*) AS n_recordings, sum(duration_s) / 3600.0 AS hours
    FROM lab.recording
    GROUP BY session_id
) AS rc USING (session_id)
GROUP BY 1, 2;
COMMENT ON MATERIALIZED VIEW lab.mv_monthly_throughput IS
    'Sessions, recordings and hours recorded per month and study. Stored: refresh it after loading data.';
CREATE UNIQUE INDEX mv_monthly_throughput_key ON lab.mv_monthly_throughput (month, study_code);
