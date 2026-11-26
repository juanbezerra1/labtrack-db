-- 0006: a star schema for reporting, as views in their own schema.
--
-- The tables in "lab" are built for writing correct data (many small tables, constraints). Tools
-- like Power BI prefer the opposite: a few wide dimension tables around fact tables, with one integer
-- key per row. These views reshape the same data that way, so nothing is copied and nothing drifts.

CREATE SCHEMA bi;
COMMENT ON SCHEMA bi IS 'Reporting views: dimensions (who, what, when) and facts (what happened). Read-only.';

-- A calendar. Power BI's time intelligence wants a complete date table, so this one is generated.
CREATE VIEW bi.dim_date AS
SELECT d::date                                   AS date_key,
       extract(year    FROM d)::integer          AS year,
       extract(quarter FROM d)::integer          AS quarter,
       extract(month   FROM d)::integer          AS month_no,
       to_char(d, 'YYYY-MM')                     AS year_month,
       to_char(d, 'Mon')                         AS month_name,
       date_trunc('month', d)::date              AS month_start,
       extract(isodow  FROM d)::integer          AS iso_weekday,
       to_char(d, 'Dy')                          AS weekday_name,
       extract(isodow  FROM d) >= 6              AS is_weekend
FROM generate_series(date '2023-01-01', date '2028-12-31', interval '1 day') AS g(d);

CREATE VIEW bi.dim_study AS
SELECT study_id AS study_key, code AS study_code, title, started_on, ended_on, planned_visits, target_n
FROM lab.study;

CREATE VIEW bi.dim_participant AS
SELECT participant_id AS participant_key, code AS participant_code, birth_year, sex, dominant_hand,
       consent_signed_on, withdrawn_on, withdrawn_on IS NOT NULL AS is_withdrawn
FROM lab.participant;

CREATE VIEW bi.dim_researcher AS
SELECT researcher_id AS researcher_key, full_name, role::text AS role, hired_on, left_on
FROM lab.researcher;

CREATE VIEW bi.dim_device AS
SELECT device_id AS device_key, kind::text AS kind, model, serial_no, home_room, acquired_on, retired_on
FROM lab.device;

-- One row per session. Dates are the lab's local calendar day (America/Sao_Paulo).
CREATE VIEW bi.fact_session AS
SELECT s.session_id                                                         AS session_key,
       (s.starts_at AT TIME ZONE 'America/Sao_Paulo')::date                 AS date_key,
       s.study_id                                                           AS study_key,
       s.participant_id                                                     AS participant_key,
       s.researcher_id                                                      AS researcher_key,
       e.group_label,
       s.visit_no,
       s.room,
       s.status::text                                                       AS status,
       s.duration_min,
       (s.starts_at AT TIME ZONE 'America/Sao_Paulo')                       AS starts_local,
       coalesce(rc.n_recordings, 0)                                         AS n_recordings,
       round(coalesce(rc.hours, 0)::numeric, 3)                             AS hours_recorded
FROM lab.session AS s
JOIN lab.enrollment AS e USING (study_id, participant_id)
LEFT JOIN (
    SELECT session_id, count(*) AS n_recordings, sum(duration_s) / 3600.0 AS hours
    FROM lab.recording GROUP BY session_id
) AS rc USING (session_id);

-- One row per recording, with its trial counts.
CREATE VIEW bi.fact_recording AS
SELECT rec.recording_id                                                     AS recording_key,
       rec.session_id                                                       AS session_key,
       (rec.recorded_at AT TIME ZONE 'America/Sao_Paulo')::date             AS date_key,
       rec.device_id                                                        AS device_key,
       rec.modality::text                                                   AS modality,
       rec.sampling_rate_hz,
       rec.n_channels,
       rec.duration_s,
       round(rec.size_bytes / 1048576.0, 2)                                 AS size_mb,
       rec.qc::text                                                         AS qc,
       coalesce(tc.n_trials, 0)                                             AS n_trials,
       coalesce(tc.n_valid, 0)                                              AS n_valid_trials
FROM lab.recording AS rec
LEFT JOIN (
    SELECT recording_id, count(*) AS n_trials, count(*) FILTER (WHERE valid) AS n_valid
    FROM lab.trial GROUP BY recording_id
) AS tc USING (recording_id);

-- One row per trial, with two headline features pivoted into columns (NULL when they do not apply).
CREATE VIEW bi.fact_trial AS
SELECT t.trial_id                                                           AS trial_key,
       t.recording_id                                                       AS recording_key,
       rec.session_id                                                       AS session_key,
       (rec.recorded_at AT TIME ZONE 'America/Sao_Paulo')::date             AS date_key,
       rec.modality::text                                                   AS modality,
       t.condition,
       t.trial_no,
       t.onset_s,
       t.duration_s,
       t.valid,
       t.reject_reason,
       round((avg(tf.value) FILTER (WHERE tf.feature_id = 1))::numeric, 3)  AS rms_mean_uv,
       round((max(tf.value) FILTER (WHERE tf.feature_id = 14))::numeric, 3) AS peak_force_n
FROM lab.trial AS t
JOIN lab.recording AS rec USING (recording_id)
LEFT JOIN lab.trial_feature AS tf ON tf.trial_id = t.trial_id AND tf.feature_id IN (1, 14)
GROUP BY t.trial_id, rec.session_id, rec.recorded_at, rec.modality;

COMMENT ON VIEW bi.dim_date        IS 'Calendar, one row per day 2023-2028 (generated), for time intelligence in BI tools.';
COMMENT ON VIEW bi.dim_study       IS 'Dimension: studies.';
COMMENT ON VIEW bi.dim_participant IS 'Dimension: participants (pseudonymised).';
COMMENT ON VIEW bi.dim_researcher  IS 'Dimension: researchers.';
COMMENT ON VIEW bi.dim_device      IS 'Dimension: devices.';
COMMENT ON VIEW bi.fact_session    IS 'Fact: one row per session, with its local date and the recordings it produced.';
COMMENT ON VIEW bi.fact_recording  IS 'Fact: one row per recording, with its size and trial counts.';
COMMENT ON VIEW bi.fact_trial      IS 'Fact: one row per trial, with two headline features (RMS and peak force) as columns.';
