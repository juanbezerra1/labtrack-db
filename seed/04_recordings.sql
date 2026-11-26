-- seed 04: recordings, channels and trials of every completed session.
--
-- What each study records in a session (the "recipe"): modality, block, sampling rate, channels, and
-- the kind of device that produces it. A recording is a file of raw signal; the database only keeps
-- its hash, size and location, and what happened inside it (the trials).

CREATE TABLE lab_seed.recipe (
    study_code text, rec_ix integer, modality lab.modality, block_no integer,
    kind text, rate_hz integer, n_channels integer, ext text,
    PRIMARY KEY (study_code, rec_ix)
);
INSERT INTO lab_seed.recipe (study_code, rec_ix, modality, block_no, kind, rate_hz, n_channels, ext) VALUES
    ('FFB-01', 1, 'emg',   1, 'emg_amplifier', 2000, 4, 'edf'),
    ('FFB-01', 2, 'force', 1, 'dynamometer',   1000, 1, 'csv'),
    ('EEG-02', 1, 'eeg',   1, 'eeg_amplifier',  500, 8, 'edf'),
    ('EEG-02', 2, 'emg',   1, 'emg_amplifier', 2000, 2, 'edf'),
    ('EMG-03', 1, 'emg',   1, 'emg_amplifier', 2000, 4, 'edf'),
    ('EMG-03', 2, 'emg',   2, 'emg_amplifier', 2000, 4, 'edf');

CREATE TABLE lab_seed.rec_plan AS
SELECT s.session_id, st.code AS study_code, p.code AS participant_code, s.visit_no,
       r.rec_ix, r.modality, r.block_no, r.rate_hz, r.n_channels, sd.device_id,
       s.starts_at + interval '5 minutes' + (r.rec_ix - 1) * interval '28 minutes' AS recorded_at,
       lab_seed.between_('n-trials:' || s.session_id || ':' || r.rec_ix, 20, 36) AS n_trials,
       format('s3://labtrack-demo/%s/%s/visit%s_%s_b%s.%s',
              st.code, p.code, s.visit_no, r.modality, r.block_no, r.ext) AS storage_uri
FROM lab.session AS s
JOIN lab.study       AS st USING (study_id)
JOIN lab.participant AS p  USING (participant_id)
JOIN lab_seed.recipe AS r  ON r.study_code = st.code
JOIN lab.session_device AS sd ON sd.session_id = s.session_id
JOIN lab.device      AS d  ON d.device_id = sd.device_id AND d.kind::text = r.kind
WHERE s.status = 'completed';

-- Recordings. Each trial takes 12 s (about 6 s of effort and rest), plus 4 s of lead-in. A recording
-- is "pending" review for two weeks, then passes (88%), is flagged (7%) or is rejected (3%).
INSERT INTO lab.recording (session_id, device_id, modality, block_no, sampling_rate_hz, n_channels,
                           recorded_at, duration_s, size_bytes, sha256, storage_uri, qc)
SELECT rp.session_id, rp.device_id, rp.modality, rp.block_no, rp.rate_hz, rp.n_channels,
       rp.recorded_at,
       rp.n_trials * 12 + 4,
       ((rp.n_trials * 12 + 4)::bigint * rp.rate_hz * rp.n_channels * 4) + 4096,
       encode(sha256(convert_to(rp.storage_uri, 'UTF8')), 'hex'),
       rp.storage_uri,
       CASE WHEN rp.recorded_at > (lab_seed.as_of() - 14)::timestamp AT TIME ZONE 'America/Sao_Paulo' THEN 'pending'
            WHEN lab_seed.u('qc:' || rp.storage_uri) < 0.88 THEN 'passed'
            WHEN lab_seed.u('qc:' || rp.storage_uri) < 0.95 THEN 'flagged'
            ELSE 'rejected' END::lab.qc_status
FROM lab_seed.rec_plan AS rp
ORDER BY rp.recorded_at, rp.session_id, rp.rec_ix;

INSERT INTO lab.channel (recording_id, channel_no, label, unit)
SELECT rec.recording_id, ch.n,
       CASE rec.modality
            WHEN 'emg' THEN (ARRAY['biceps', 'triceps', 'flexor_carpi', 'extensor_carpi'])[ch.n]
            WHEN 'eeg' THEN (ARRAY['Fz', 'Cz', 'Pz', 'C3', 'C4', 'O1', 'O2', 'Oz'])[ch.n]
            ELSE 'grip_force' END,
       CASE rec.modality WHEN 'force' THEN 'N' ELSE 'uV' END
FROM lab.recording AS rec
CROSS JOIN LATERAL generate_series(1, rec.n_channels::integer) AS ch (n)
ORDER BY rec.recording_id, ch.n;

-- Trials. FFB-01 alternates six conditions (three force levels, with and without the feedback);
-- EEG-02 alternates a small and a large visual stimulus; EMG-03 has a block before and a block after
-- a fatiguing task. Some trials are rejected, far more often in recordings that failed review.
INSERT INTO lab.trial (recording_id, trial_no, condition, onset_s, duration_s, valid, reject_reason)
SELECT t.recording_id, t.k, t.condition, t.onset_s, t.duration_s, t.valid,
       CASE WHEN NOT t.valid THEN (ARRAY['movement_artifact', 'electrode_noise', 'force_overshoot', 'late_onset'])
                                    [1 + floor(lab_seed.u('why:' || t.recording_id || ':' || t.k) * 4)::integer] END
FROM (
    SELECT rec.recording_id, k,
           CASE rp.study_code
                WHEN 'FFB-01' THEN (ARRAY['hold_20_fb', 'hold_20_nofb', 'hold_40_fb', 'hold_40_nofb', 'hold_60_fb', 'hold_60_nofb'])[1 + (k - 1) % 6]
                WHEN 'EEG-02' THEN (ARRAY['stimulus_small', 'stimulus_large'])[1 + (k - 1) % 2]
                ELSE CASE WHEN rp.block_no = 1 THEN 'fatigue_pre' ELSE 'fatigue_post' END
           END AS condition,
           round((2 + (k - 1) * 12 + 1.5 * lab_seed.u('onset:' || rec.recording_id || ':' || k))::numeric, 3) AS onset_s,
           round((5.5 + lab_seed.u('dur:' || rec.recording_id || ':' || k))::numeric, 3) AS duration_s,
           lab_seed.u('valid:' || rec.recording_id || ':' || k) <
               CASE rec.qc WHEN 'passed' THEN 0.96 WHEN 'flagged' THEN 0.75 WHEN 'rejected' THEN 0.35 ELSE 0.93 END AS valid
    FROM lab.recording AS rec
    JOIN lab_seed.rec_plan AS rp ON rp.storage_uri = rec.storage_uri
    CROSS JOIN LATERAL generate_series(1, rp.n_trials) AS k
) AS t
ORDER BY t.recording_id, t.k;
