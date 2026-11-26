-- 0004: the feature catalogue and the long, narrow table of feature values (the big one).
--
-- "Long" format: one row per (trial, channel, feature) instead of one column per feature. It is
-- narrow, it never needs ALTER TABLE for a new feature, and it is exactly what makes the EXPLAIN lab
-- interesting: ten million small rows and a handful of ways to ask for them.

CREATE TABLE lab.feature_def (
    feature_id   smallint PRIMARY KEY,
    modality     lab.modality NOT NULL,
    name         text     NOT NULL,
    unit         text     NOT NULL,
    description  text     NOT NULL,
    UNIQUE (modality, name)
);
COMMENT ON TABLE lab.feature_def IS 'Reference data: which features exist for which modality. Loaded by this migration.';

INSERT INTO lab.feature_def (feature_id, modality, name, unit, description) VALUES
    ( 1, 'emg',   'rms',            'uV',     'Root mean square amplitude of the trial'),
    ( 2, 'emg',   'mav',            'uV',     'Mean absolute value'),
    ( 3, 'emg',   'wl',             'uV',     'Waveform length: summed absolute first difference'),
    ( 4, 'emg',   'zc',             'count',  'Zero crossings'),
    ( 5, 'emg',   'ssc',            'count',  'Slope sign changes'),
    ( 6, 'emg',   'mnf',            'Hz',     'Mean frequency of the power spectrum'),
    ( 7, 'emg',   'mdf',            'Hz',     'Median frequency of the power spectrum'),
    ( 8, 'emg',   'iemg',           'uV*s',   'Integrated EMG: area under the rectified signal'),
    ( 9, 'eeg',   'power_delta',    'uV^2',   'Band power, 1-4 Hz'),
    (10, 'eeg',   'power_theta',    'uV^2',   'Band power, 4-8 Hz'),
    (11, 'eeg',   'power_alpha',    'uV^2',   'Band power, 8-13 Hz'),
    (12, 'eeg',   'power_beta',     'uV^2',   'Band power, 13-30 Hz'),
    (13, 'eeg',   'power_gamma',    'uV^2',   'Band power, 30-45 Hz'),
    (14, 'force', 'peak_force',     'N',      'Maximum force in the trial'),
    (15, 'force', 'mean_force',     'N',      'Mean force during the hold phase'),
    (16, 'force', 'rise_time',      's',      'Time to reach 90% of the plateau'),
    (17, 'force', 'force_cv',       '%',      'Coefficient of variation of the force during the hold phase');

CREATE TABLE lab.trial_feature (
    trial_id     bigint   NOT NULL REFERENCES lab.trial (trial_id) ON DELETE CASCADE,
    channel_no   smallint NOT NULL,
    feature_id   smallint NOT NULL REFERENCES lab.feature_def (feature_id),
    value        double precision NOT NULL,
    PRIMARY KEY (trial_id, channel_no, feature_id),
    CONSTRAINT trial_feature_channel_positive CHECK (channel_no >= 1),
    -- NaN compares equal to itself in PostgreSQL, so test for it explicitly; also refuse infinities.
    CONSTRAINT trial_feature_finite CHECK (value <> 'NaN'::float8 AND value NOT IN ('Infinity'::float8, '-Infinity'::float8))
);
COMMENT ON TABLE  lab.trial_feature IS 'The long table: one value per trial, channel and feature. The only index is the primary key, on purpose (see explain-lab/).';
COMMENT ON COLUMN lab.trial_feature.channel_no IS 'Refers to lab.channel through the trial''s recording; not a foreign key because the pair (recording, channel) is not a column of this table.';

-- Column comments (they feed docs/data-dictionary.md, which is generated from the catalog).
COMMENT ON COLUMN lab.feature_def.feature_id IS 'Small stable number used by lab.trial_feature.';
COMMENT ON COLUMN lab.feature_def.modality IS 'The kind of recording the feature is computed from.';
COMMENT ON COLUMN lab.feature_def.name IS 'Short name such as rms or force_cv; unique within a modality.';
COMMENT ON COLUMN lab.feature_def.unit IS 'Unit of the value.';
COMMENT ON COLUMN lab.feature_def.description IS 'What the feature measures.';
COMMENT ON COLUMN lab.trial_feature.trial_id IS 'The trial the value was computed for.';
COMMENT ON COLUMN lab.trial_feature.feature_id IS 'Which feature (see lab.feature_def).';
COMMENT ON COLUMN lab.trial_feature.value IS 'The computed value, in the unit of the feature. Never NaN or infinite (enforced).';
