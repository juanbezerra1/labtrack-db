-- seed 05: the long table, one row per (trial, channel, feature). By far the biggest table: roughly
-- 1.1 million rows at medium scale, ~10 million at large.
--
-- Values are plausible, not real. They come from simple formulas of the effort level, the participant,
-- the channel and a hash-based noise term, with a few effects PLANTED on purpose so the teaching
-- queries have something to find:
--   * force_cv is lower when the feedback is on, and lower still in the intervention group,
--   * mean and median EMG frequency drop (and RMS rises) after the fatiguing task of EMG-03,
--   * alpha power is lower with the large visual stimulus of EEG-02, and highest at the occipital channels.
-- No arithmetic beyond + - * / and rounding to 3 decimals is used, so the numbers are identical on
-- every platform.

CREATE FUNCTION lab_seed.feature_value(
    feature_id   smallint,
    noise        float8,     -- [0, 1)
    lvl          float8,     -- effort level, share of the maximum (0.2 .. 0.6), 0.5 when it does not apply
    pf           float8,     -- participant factor, about 1
    ch_gain      float8,     -- channel gain
    feedback     boolean,
    intervention boolean,
    fatigued     boolean,
    big_stimulus boolean,
    female       boolean
) RETURNS float8
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    AS $$
    SELECT round(1000 * (0.9 + 0.2 * noise) * CASE feature_id
        -- EMG
        WHEN  1 THEN (30 + 260 * lvl) * pf * ch_gain * CASE WHEN fatigued THEN 1.12 ELSE 1.0 END
        WHEN  2 THEN 0.80 * (30 + 260 * lvl) * pf * ch_gain * CASE WHEN fatigued THEN 1.12 ELSE 1.0 END
        WHEN  3 THEN 70   * (30 + 260 * lvl) * pf * ch_gain * CASE WHEN fatigued THEN 1.12 ELSE 1.0 END
        WHEN  4 THEN 95 - 40 * lvl
        WHEN  5 THEN 110 - 35 * lvl
        WHEN  6 THEN (92 - 22 * lvl) * CASE WHEN fatigued THEN 0.86 ELSE 1.0 END
        WHEN  7 THEN (78 - 18 * lvl) * CASE WHEN fatigued THEN 0.84 ELSE 1.0 END
        WHEN  8 THEN 4.8  * (30 + 260 * lvl) * pf * ch_gain * CASE WHEN fatigued THEN 1.12 ELSE 1.0 END
        -- EEG band powers
        WHEN  9 THEN 12  * pf
        WHEN 10 THEN 8   * pf
        WHEN 11 THEN 20  * pf * ch_gain * CASE WHEN big_stimulus THEN 0.85 ELSE 1.0 END
        WHEN 12 THEN 6   * pf
        WHEN 13 THEN 1.5 * pf
        -- force
        WHEN 14 THEN lvl * CASE WHEN female THEN 260 ELSE 380 END * pf
        WHEN 15 THEN 0.93 * lvl * CASE WHEN female THEN 260 ELSE 380 END * pf
        WHEN 16 THEN 0.9 + 1.2 * lvl
        WHEN 17 THEN (5.5 - 2.5 * lvl) * (1 - CASE WHEN feedback THEN CASE WHEN intervention THEN 0.18 ELSE 0.04 END ELSE 0.0 END)
    END) / 1000::float8
    $$;

DO $$
DECLARE
    first_id bigint;
    last_id  bigint;
    step     constant integer := 20000;      -- trials per chunk: keeps each sort small
BEGIN
    SELECT min(trial_id), max(trial_id) INTO first_id, last_id FROM lab.trial;
    IF first_id IS NULL THEN
        RETURN;
    END IF;
    PERFORM set_config('work_mem', '128MB', true);
    WHILE first_id <= last_id LOOP
        INSERT INTO lab.trial_feature (trial_id, channel_no, feature_id, value)
        SELECT t.trial_id, ch.n, f.feature_id,
               lab_seed.feature_value(
                   f.feature_id,
                   lab_seed.u('v:' || t.trial_id || ':' || ch.n || ':' || f.feature_id),
                   CASE WHEN left(t.condition, 5) = 'hold_' THEN substr(t.condition, 6, 2)::integer / 100.0 ELSE 0.5 END,
                   0.8 + 0.4 * lab_seed.u('pf:' || s.participant_id),
                   CASE WHEN rec.modality = 'emg' THEN (ARRAY[1.0, 0.6, 0.85, 0.7])[ch.n]
                        WHEN rec.modality = 'eeg' AND ch.n >= 6 THEN 1.8
                        ELSE 1.0 END,
                   right(t.condition, 3) = '_fb',
                   e.group_label = 'intervention',
                   t.condition = 'fatigue_post',
                   t.condition = 'stimulus_large',
                   p.sex = 'F')
        FROM lab.trial AS t
        JOIN lab.recording   AS rec ON rec.recording_id = t.recording_id
        JOIN lab.session     AS s   ON s.session_id = rec.session_id
        JOIN lab.participant AS p   ON p.participant_id = s.participant_id
        JOIN lab.enrollment  AS e   ON e.study_id = s.study_id AND e.participant_id = s.participant_id
        CROSS JOIN LATERAL generate_series(1, rec.n_channels::integer) AS ch (n)
        JOIN lab.feature_def AS f   ON f.modality = rec.modality
        WHERE t.trial_id BETWEEN first_id AND first_id + step - 1
        ORDER BY t.trial_id, ch.n, f.feature_id;
        first_id := first_id + step;
    END LOOP;
END
$$;
