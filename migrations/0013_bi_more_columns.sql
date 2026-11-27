-- 0013: the star schema learns four more features and one data-quality flag.
--
-- A report on the star schema (the labtrack-bi project) asks two things the views could not answer yet: how the
-- frequency content of the EMG, the alpha power of the EEG and the force variability behave next to the trial,
-- and which recordings were made with a device that had no valid calibration that day. Query 04 lists those
-- recordings per device; a report wants a column it can filter on.
--
-- CREATE OR REPLACE VIEW may add columns only at the END of the list and may not rename or retype the ones that
-- exist, which is exactly what a tool that already reads these views needs: nothing it knows changes. It is a
-- catalog update (an instant lock, no table is rewritten), and the grants on the views are kept.

-- Six features per trial instead of two. Each feature exists for one modality only, so the other columns are NULL
-- for a trial of another modality. Averages are over the channels of the recording (EMG has 2 to 4, EEG has 8, the
-- force sensor has 1); rounded to 3 decimals like the two columns that were already there.
CREATE OR REPLACE VIEW bi.fact_trial AS
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
       round((max(tf.value) FILTER (WHERE tf.feature_id = 14))::numeric, 3) AS peak_force_n,
       round((avg(tf.value) FILTER (WHERE tf.feature_id = 17))::numeric, 3) AS force_cv_pct,
       round((avg(tf.value) FILTER (WHERE tf.feature_id = 6))::numeric, 3)  AS mnf_hz,
       round((avg(tf.value) FILTER (WHERE tf.feature_id = 7))::numeric, 3)  AS mdf_hz,
       round((avg(tf.value) FILTER (WHERE tf.feature_id = 11))::numeric, 3) AS alpha_power_uv2
FROM lab.trial AS t
JOIN lab.recording AS rec USING (recording_id)
LEFT JOIN lab.trial_feature AS tf ON tf.trial_id = t.trial_id AND tf.feature_id IN (1, 6, 7, 11, 14, 17)
GROUP BY t.trial_id, rec.session_id, rec.recorded_at, rec.modality;

-- The calibration rule of query 04 as a column: a recording is fine when SOME passed calibration of its device
-- covers the lab's calendar day of the recording (from performed_on up to, not including, valid_until).
CREATE OR REPLACE VIEW bi.fact_recording AS
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
       coalesce(tc.n_valid, 0)                                              AS n_valid_trials,
       EXISTS (
           SELECT 1
           FROM lab.calibration AS c
           WHERE c.device_id = rec.device_id
             AND c.passed
             AND c.performed_on <= (rec.recorded_at AT TIME ZONE 'America/Sao_Paulo')::date
             AND (rec.recorded_at AT TIME ZONE 'America/Sao_Paulo')::date < c.valid_until) AS device_calibrated
FROM lab.recording AS rec
LEFT JOIN (
    SELECT recording_id, count(*) AS n_trials, count(*) FILTER (WHERE valid) AS n_valid
    FROM lab.trial GROUP BY recording_id
) AS tc USING (recording_id);

COMMENT ON VIEW bi.fact_trial IS
    'Fact: one row per trial, with the features of its modality as columns (NULL for a trial of another modality).';
COMMENT ON COLUMN bi.fact_trial.rms_mean_uv IS 'EMG: root mean square amplitude, in microvolts, averaged over the channels.';
COMMENT ON COLUMN bi.fact_trial.peak_force_n IS 'Force: the highest force of the trial, in newtons.';
COMMENT ON COLUMN bi.fact_trial.force_cv_pct IS 'Force: coefficient of variation of the force in the hold phase, in percent. Lower is steadier.';
COMMENT ON COLUMN bi.fact_trial.mnf_hz IS 'EMG: mean frequency of the power spectrum, in hertz, averaged over the channels.';
COMMENT ON COLUMN bi.fact_trial.mdf_hz IS 'EMG: median frequency of the power spectrum, in hertz, averaged over the channels.';
COMMENT ON COLUMN bi.fact_trial.alpha_power_uv2 IS 'EEG: band power at 8 to 13 Hz, in microvolts squared, averaged over the channels.';
COMMENT ON COLUMN bi.fact_recording.device_calibrated IS
    'true when some passed calibration of the device covered the day of the recording (lab calendar day); false is a data-quality finding, see query 04.';
