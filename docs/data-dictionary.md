# Data dictionary

Generated from the database by `labtrack dictionary`; do not edit by hand. The descriptions are the
`COMMENT ON` statements of the migrations.

## lab.calibration

*table.* One row per calibration round of a device. A failed round (passed = false) covers nothing and is usually repeated.

| column | type | null | default | description |
|---|---|---|---|---|
| `calibration_id` | integer |  | identity | Surrogate key, assigned by the database. |
| `device_id` | integer |  |  | The device that was calibrated. |
| `performed_on` | date |  |  | Day of the calibration round. |
| `performed_by` | integer |  |  | The researcher (a technician, usually) who did it. |
| `passed` | boolean |  |  | False when the device was out of tolerance; such a round covers nothing. |
| `valid_until` | date |  |  | Last day (exclusive) on which this calibration covers the device. Only counts when passed is true. |
| `notes` | text | yes |  | Free text; filled in when something went wrong. |

Constraints:

- `calibration_dates_ordered`: `CHECK (valid_until > performed_on)`
- `calibration_device_id_fkey`: `FOREIGN KEY (device_id) REFERENCES lab.device(device_id)`
- `calibration_performed_by_fkey`: `FOREIGN KEY (performed_by) REFERENCES lab.researcher(researcher_id)`
- `calibration_pkey`: `PRIMARY KEY (calibration_id)`
- `calibration_device_id_performed_on_key`: `UNIQUE (device_id, performed_on)`

Indexes:

- `calibration_device_id_performed_on_key`: `CREATE UNIQUE INDEX calibration_device_id_performed_on_key ON lab.calibration USING btree (device_id, performed_on)`
- `calibration_performed_by_idx`: `CREATE INDEX calibration_performed_by_idx ON lab.calibration USING btree (performed_by)`
- `calibration_pkey`: `CREATE UNIQUE INDEX calibration_pkey ON lab.calibration USING btree (calibration_id)`

## lab.channel

*table.* The channels of a recording: which electrode or sensor each column of the signal came from.

| column | type | null | default | description |
|---|---|---|---|---|
| `recording_id` | bigint |  |  | The recording. |
| `channel_no` | smallint |  |  | 1 to n_channels: the column of the signal this row describes. |
| `label` | text |  |  | Electrode or sensor name, such as biceps or Cz. |
| `unit` | text |  |  | Unit of the signal: uV, mV, V or N. |

Constraints:

- `channel_no_positive`: `CHECK (channel_no >= 1)`
- `channel_unit_values`: `CHECK (unit = ANY (ARRAY['uV'::text, 'mV'::text, 'V'::text, 'N'::text]))`
- `channel_recording_id_fkey`: `FOREIGN KEY (recording_id) REFERENCES lab.recording(recording_id) ON DELETE CASCADE`
- `channel_pkey`: `PRIMARY KEY (recording_id, channel_no)`

Indexes:

- `channel_pkey`: `CREATE UNIQUE INDEX channel_pkey ON lab.channel USING btree (recording_id, channel_no)`

## lab.device

*table.* Amplifiers, dynamometers and stimulators. home_room is where the device normally lives.

| column | type | null | default | description |
|---|---|---|---|---|
| `device_id` | integer |  | identity | Surrogate key, assigned by the database. |
| `kind` | lab.device_kind |  |  | emg_amplifier, eeg_amplifier, dynamometer or stimulator. |
| `model` | text |  |  | Model name. |
| `serial_no` | text |  |  | Manufacturer serial number, unique. |
| `home_room` | text |  |  | Room where the device normally lives, such as R03. |
| `acquired_on` | date |  |  | Day the lab got the device. |
| `retired_on` | date | yes |  | Day it was taken out of service; NULL while in use. |

Constraints:

- `device_dates_ordered`: `CHECK (retired_on IS NULL OR retired_on > acquired_on)`
- `device_room_format`: `CHECK (home_room ~ '^R[0-9]{2}$'::text)`
- `device_pkey`: `PRIMARY KEY (device_id)`
- `device_serial_no_key`: `UNIQUE (serial_no)`

Indexes:

- `device_pkey`: `CREATE UNIQUE INDEX device_pkey ON lab.device USING btree (device_id)`
- `device_serial_no_key`: `CREATE UNIQUE INDEX device_serial_no_key ON lab.device USING btree (serial_no)`

## lab.enrollment

*table.* Which participant takes part in which study, and in which group. The primary key is the pair, so nobody is enrolled twice in a study.

| column | type | null | default | description |
|---|---|---|---|---|
| `study_id` | integer |  |  | The study. |
| `participant_id` | integer |  |  | The participant. |
| `group_label` | text |  |  | control or intervention. Assigned at enrollment and never changed. |
| `enrolled_on` | date |  |  | Day the participant joined the study; no session may be earlier. |

Constraints:

- `enrollment_group_values`: `CHECK (group_label = ANY (ARRAY['control'::text, 'intervention'::text]))`
- `enrollment_participant_id_fkey`: `FOREIGN KEY (participant_id) REFERENCES lab.participant(participant_id)`
- `enrollment_study_id_fkey`: `FOREIGN KEY (study_id) REFERENCES lab.study(study_id)`
- `enrollment_pkey`: `PRIMARY KEY (study_id, participant_id)`

Indexes:

- `enrollment_participant_idx`: `CREATE INDEX enrollment_participant_idx ON lab.enrollment USING btree (participant_id)`
- `enrollment_pkey`: `CREATE UNIQUE INDEX enrollment_pkey ON lab.enrollment USING btree (study_id, participant_id)`

## lab.feature_def

*table.* Reference data: which features exist for which modality. Loaded by this migration.

| column | type | null | default | description |
|---|---|---|---|---|
| `feature_id` | smallint |  |  | Small stable number used by lab.trial_feature. |
| `modality` | lab.modality |  |  | The kind of recording the feature is computed from. |
| `name` | text |  |  | Short name such as rms or force_cv; unique within a modality. |
| `unit` | text |  |  | Unit of the value. |
| `description` | text |  |  | What the feature measures. |

Constraints:

- `feature_def_pkey`: `PRIMARY KEY (feature_id)`
- `feature_def_modality_name_key`: `UNIQUE (modality, name)`

Indexes:

- `feature_def_modality_name_key`: `CREATE UNIQUE INDEX feature_def_modality_name_key ON lab.feature_def USING btree (modality, name)`
- `feature_def_pkey`: `CREATE UNIQUE INDEX feature_def_pkey ON lab.feature_def USING btree (feature_id)`

## lab.participant

*table.* One row per person. Pseudonymised by design: a code, a birth year and nothing that identifies anyone.

| column | type | null | default | description |
|---|---|---|---|---|
| `participant_id` | integer |  | identity | Surrogate key, assigned by the database. |
| `code` | text |  |  | Pseudonym such as P0042. The link to a real person, if any, lives outside this database. |
| `birth_year` | smallint |  |  | Year only, never the full date: enough for age analyses, not enough to identify anyone. |
| `sex` | character(1) |  |  | F or M, as recorded for the study. |
| `dominant_hand` | lab.hand |  |  | right, left or ambidextrous. |
| `consent_signed_on` | date |  |  | No session may start before this day (enforced by a trigger). |
| `withdrawn_on` | date | yes |  | Day the participant withdrew; NULL while still taking part. No active session may be later than this day. |

Constraints:

- `participant_birth_range`: `CHECK (birth_year >= 1930 AND birth_year <= 2010)`
- `participant_code_format`: `CHECK (code ~ '^P[0-9]{4,6}$'::text)`
- `participant_sex_values`: `CHECK (sex = ANY (ARRAY['F'::bpchar, 'M'::bpchar]))`
- `participant_withdrawal_ordered`: `CHECK (withdrawn_on IS NULL OR withdrawn_on >= consent_signed_on)`
- `participant_pkey`: `PRIMARY KEY (participant_id)`
- `participant_code_key`: `UNIQUE (code)`

Indexes:

- `participant_code_key`: `CREATE UNIQUE INDEX participant_code_key ON lab.participant USING btree (code)`
- `participant_pkey`: `CREATE UNIQUE INDEX participant_pkey ON lab.participant USING btree (participant_id)`

## lab.recording

*table.* A file of raw signal. The signal itself stays in storage; the database keeps what you need to find and trust it.

| column | type | null | default | description |
|---|---|---|---|---|
| `recording_id` | bigint |  | identity | Surrogate key, assigned by the database. |
| `session_id` | bigint |  |  | The session in which the signal was recorded. |
| `device_id` | integer |  |  | The device that recorded it; must be one booked for the session. |
| `modality` | lab.modality |  |  | emg, eeg or force. |
| `block_no` | smallint |  | 1 | Which block of the session, when a modality is recorded more than once (before and after a task, say). |
| `sampling_rate_hz` | integer |  |  | Samples per second, per channel. |
| `n_channels` | smallint |  |  | How many channels the file has; lab.channel has one row for each. |
| `recorded_at` | timestamp with time zone |  |  | When the recording started. |
| `duration_s` | numeric(8,2) |  |  | Length of the recording in seconds. |
| `size_bytes` | bigint |  |  | Size of the file. |
| `sha256` | character(64) |  |  | Hash of the file. UNIQUE, so the same recording cannot be registered twice. |
| `storage_uri` | text |  |  | Where the file is: s3://bucket/path or file:///path. |
| `qc` | lab.qc_status |  | 'pending'::lab.qc_status | Quality-control state: pending until someone reviews the recording, then passed, flagged (usable with care) or rejected. |

Constraints:

- `recording_channels_range`: `CHECK (n_channels >= 1 AND n_channels <= 256)`
- `recording_duration_positive`: `CHECK (duration_s > 0::numeric)`
- `recording_rate_range`: `CHECK (sampling_rate_hz >= 1 AND sampling_rate_hz <= 100000)`
- `recording_sha256_format`: `CHECK (sha256 ~ '^[0-9a-f]{64}$'::text)`
- `recording_size_nonnegative`: `CHECK (size_bytes >= 0)`
- `recording_uri_scheme`: `CHECK (storage_uri ~ '^(s3\|file)://'::text)`
- `recording_session_device_fk`: `FOREIGN KEY (session_id, device_id) REFERENCES lab.session_device(session_id, device_id)`
- `recording_pkey`: `PRIMARY KEY (recording_id)`
- `recording_block_unique`: `UNIQUE (session_id, modality, block_no)`
- `recording_sha256_key`: `UNIQUE (sha256)`

Indexes:

- `recording_block_unique`: `CREATE UNIQUE INDEX recording_block_unique ON lab.recording USING btree (session_id, modality, block_no)`
- `recording_device_idx`: `CREATE INDEX recording_device_idx ON lab.recording USING btree (device_id)`
- `recording_pkey`: `CREATE UNIQUE INDEX recording_pkey ON lab.recording USING btree (recording_id)`
- `recording_recorded_at_idx`: `CREATE INDEX recording_recorded_at_idx ON lab.recording USING btree (recorded_at)`
- `recording_sha256_key`: `CREATE UNIQUE INDEX recording_sha256_key ON lab.recording USING btree (sha256)`

## lab.researcher

*table.* Lab staff. The data in this repository is synthetic: names and e-mails are invented.

| column | type | null | default | description |
|---|---|---|---|---|
| `researcher_id` | integer |  | identity | Surrogate key, assigned by the database. |
| `full_name` | text |  |  | Invented name (the data in this repository is synthetic). |
| `role` | lab.researcher_role |  |  | pi, postdoc, phd, msc or technician. |
| `email` | text |  |  | Unique address, also invented: the domain ends in .example, a name reserved for documentation that never resolves. |
| `hired_on` | date |  |  | First day in the lab. |
| `left_on` | date | yes |  | Day the person left; NULL while still employed. |

Constraints:

- `researcher_dates_ordered`: `CHECK (left_on IS NULL OR left_on > hired_on)`
- `researcher_email_shape`: `CHECK (email ~* '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'::text)`
- `researcher_name_length`: `CHECK (length(btrim(full_name)) >= 3)`
- `researcher_pkey`: `PRIMARY KEY (researcher_id)`
- `researcher_email_key`: `UNIQUE (email)`

Indexes:

- `researcher_email_key`: `CREATE UNIQUE INDEX researcher_email_key ON lab.researcher USING btree (email)`
- `researcher_pkey`: `CREATE UNIQUE INDEX researcher_pkey ON lab.researcher USING btree (researcher_id)`

## lab.session

*table.* One visit of one participant to the lab, in one room, run by one researcher.

| column | type | null | default | description |
|---|---|---|---|---|
| `session_id` | bigint |  | identity | Surrogate key, assigned by the database. |
| `study_id` | integer |  |  | The study; with participant_id it must exist in lab.enrollment. |
| `participant_id` | integer |  |  | The participant. |
| `researcher_id` | integer |  |  | Who ran the session. |
| `visit_no` | smallint |  |  | 1, 2, 3... in the order of the participant's visits; make-up visits continue the numbering. |
| `room` | text |  |  | Room code such as R03. |
| `starts_at` | timestamp with time zone |  |  | Start of the session (an absolute moment; the lab's local time is America/Sao_Paulo). |
| `ends_at` | timestamp with time zone |  |  | End of the session; at most six hours after the start. |
| `status` | lab.session_status |  | 'scheduled'::lab.session_status | scheduled (in the future), completed, cancelled or no_show. Only scheduled and completed sessions hold a room. |
| `notes` | jsonb |  | '{}'::jsonb | Free-form protocol notes as a JSON object (protocol version, room temperature, issues...). |
| `during` | tstzrange | yes | generated: tstzrange(starts_at, ends_at) | Generated: the time range [starts_at, ends_at). The exclusion constraint compares these. |
| `duration_min` | integer | yes | generated: ((EXTRACT(epoch FROM (ends_at - starts_at)) / (60)::numeric))::integer | Generated: the length in whole minutes. |
| `created_at` | timestamp with time zone |  | now() | When the row was inserted. |
| `updated_at` | timestamp with time zone |  | now() | When the row was last changed (maintained by a trigger). |
| `protocol_version` | text |  | 'v2'::text | Protocol version used in the session, such as v2. Was notes->>'protocol' before migration 0008. |

Constraints:

- `session_max_length`: `CHECK ((ends_at - starts_at) <= '06:00:00'::interval)`
- `session_notes_object`: `CHECK (jsonb_typeof(notes) = 'object'::text)`
- `session_protocol_format`: `CHECK (protocol_version IS NOT NULL AND protocol_version ~ '^v[0-9]+$'::text)`
- `session_room_format`: `CHECK (room ~ '^R[0-9]{2}$'::text)`
- `session_times_ordered`: `CHECK (ends_at > starts_at)`
- `session_visit_range`: `CHECK (visit_no >= 1 AND visit_no <= 20)`
- `session_enrollment_fk`: `FOREIGN KEY (study_id, participant_id) REFERENCES lab.enrollment(study_id, participant_id)`
- `session_researcher_id_fkey`: `FOREIGN KEY (researcher_id) REFERENCES lab.researcher(researcher_id)`
- `session_pkey`: `PRIMARY KEY (session_id)`
- `session_visit_unique`: `UNIQUE (study_id, participant_id, visit_no)`
- `session_room_no_overlap`: `EXCLUDE USING gist (room WITH =, during WITH &&) WHERE (status = ANY (ARRAY['scheduled'::lab.session_status, 'completed'::lab.session_status]))`

Indexes:

- `session_participant_idx`: `CREATE INDEX session_participant_idx ON lab.session USING btree (participant_id, starts_at)`
- `session_pkey`: `CREATE UNIQUE INDEX session_pkey ON lab.session USING btree (session_id)`
- `session_researcher_idx`: `CREATE INDEX session_researcher_idx ON lab.session USING btree (researcher_id)`
- `session_room_no_overlap`: `CREATE INDEX session_room_no_overlap ON lab.session USING gist (room, during) WHERE (status = ANY (ARRAY['scheduled'::lab.session_status, 'completed'::lab.session_status]))`
- `session_starts_at_idx`: `CREATE INDEX session_starts_at_idx ON lab.session USING btree (starts_at)`
- `session_visit_unique`: `CREATE UNIQUE INDEX session_visit_unique ON lab.session USING btree (study_id, participant_id, visit_no)`

## lab.session_device

*table.* The devices booked for a session. A recording may only use a device listed here (composite foreign key).

| column | type | null | default | description |
|---|---|---|---|---|
| `session_id` | bigint |  |  | The session. |
| `device_id` | integer |  |  | A device booked for it. |

Constraints:

- `session_device_device_id_fkey`: `FOREIGN KEY (device_id) REFERENCES lab.device(device_id)`
- `session_device_session_id_fkey`: `FOREIGN KEY (session_id) REFERENCES lab.session(session_id) ON DELETE CASCADE`
- `session_device_pkey`: `PRIMARY KEY (session_id, device_id)`

Indexes:

- `session_device_device_idx`: `CREATE INDEX session_device_device_idx ON lab.session_device USING btree (device_id)`
- `session_device_pkey`: `CREATE UNIQUE INDEX session_device_pkey ON lab.session_device USING btree (session_id, device_id)`

## lab.study

*table.* A study (protocol): a question, a period, a planned number of visits per participant.

| column | type | null | default | description |
|---|---|---|---|---|
| `study_id` | integer |  | identity | Surrogate key, assigned by the database. |
| `code` | text |  |  | Short stable code such as FFB-01 (letters, a dash, two digits). |
| `title` | text |  |  | Descriptive title, 5 to 200 characters. |
| `started_on` | date |  |  | First day of the study; no session may happen before it. |
| `ended_on` | date | yes |  | Last day of the study; NULL while it is still open. |
| `planned_visits` | smallint |  | 4 | How many sessions each participant is supposed to attend. |
| `target_n` | integer |  |  | How many participants the study aims to enroll. |
| `created_at` | timestamp with time zone |  | now() | When the row was inserted. |
| `updated_at` | timestamp with time zone |  | now() | When the row was last changed (maintained by a trigger). |

Constraints:

- `study_code_format`: `CHECK (code ~ '^[A-Z]{2,6}-[0-9]{2}$'::text)`
- `study_dates_ordered`: `CHECK (ended_on IS NULL OR ended_on >= started_on)`
- `study_target_positive`: `CHECK (target_n > 0)`
- `study_title_length`: `CHECK (length(title) >= 5 AND length(title) <= 200)`
- `study_visits_range`: `CHECK (planned_visits >= 1 AND planned_visits <= 20)`
- `study_pkey`: `PRIMARY KEY (study_id)`
- `study_code_key`: `UNIQUE (code)`

Indexes:

- `study_code_key`: `CREATE UNIQUE INDEX study_code_key ON lab.study USING btree (code)`
- `study_pkey`: `CREATE UNIQUE INDEX study_pkey ON lab.study USING btree (study_id)`

## lab.trial

*table.* One repetition inside a recording (for example, one 6 s contraction at 20% of maximum).

| column | type | null | default | description |
|---|---|---|---|---|
| `trial_id` | bigint |  | identity | Surrogate key, assigned by the database. |
| `recording_id` | bigint |  |  | The recording the trial belongs to. |
| `trial_no` | integer |  |  | 1, 2, 3... within the recording. |
| `condition` | text |  |  | The experimental condition of the trial, such as hold_40_fb (40% of maximum force, feedback on). |
| `onset_s` | numeric(8,3) |  |  | Seconds from the start of the recording to the start of the trial. |
| `duration_s` | numeric(6,3) |  |  | Length of the trial in seconds. |
| `valid` | boolean |  | true | False when the trial was thrown out in review; reject_reason then says why. |
| `reject_reason` | text | yes |  | Why a rejected trial was thrown out; NULL for valid trials (enforced). |

Constraints:

- `trial_duration_positive`: `CHECK (duration_s > 0::numeric)`
- `trial_number_positive`: `CHECK (trial_no >= 1)`
- `trial_onset_nonnegative`: `CHECK (onset_s >= 0::numeric)`
- `trial_reason_iff_rejected`: `CHECK (valid AND reject_reason IS NULL OR NOT valid AND reject_reason IS NOT NULL)`
- `trial_recording_id_fkey`: `FOREIGN KEY (recording_id) REFERENCES lab.recording(recording_id) ON DELETE CASCADE`
- `trial_pkey`: `PRIMARY KEY (trial_id)`
- `trial_number_unique`: `UNIQUE (recording_id, trial_no)`

Indexes:

- `trial_number_unique`: `CREATE UNIQUE INDEX trial_number_unique ON lab.trial USING btree (recording_id, trial_no)`
- `trial_pkey`: `CREATE UNIQUE INDEX trial_pkey ON lab.trial USING btree (trial_id)`

## lab.trial_feature

*table.* The long table: one value per trial, channel and feature. The only index is the primary key, on purpose (see explain-lab/).

| column | type | null | default | description |
|---|---|---|---|---|
| `trial_id` | bigint |  |  | The trial the value was computed for. |
| `channel_no` | smallint |  |  | Refers to lab.channel through the trial's recording; not a foreign key because the pair (recording, channel) is not a column of this table. |
| `feature_id` | smallint |  |  | Which feature (see lab.feature_def). |
| `value` | double precision |  |  | The computed value, in the unit of the feature. Never NaN or infinite (enforced). |

Constraints:

- `trial_feature_channel_positive`: `CHECK (channel_no >= 1)`
- `trial_feature_finite`: `CHECK (value <> 'NaN'::double precision AND (value <> ALL (ARRAY['Infinity'::double precision, '-Infinity'::double precision])))`
- `trial_feature_feature_id_fkey`: `FOREIGN KEY (feature_id) REFERENCES lab.feature_def(feature_id)`
- `trial_feature_trial_id_fkey`: `FOREIGN KEY (trial_id) REFERENCES lab.trial(trial_id) ON DELETE CASCADE`
- `trial_feature_pkey`: `PRIMARY KEY (trial_id, channel_no, feature_id)`

Indexes:

- `trial_feature_pkey`: `CREATE UNIQUE INDEX trial_feature_pkey ON lab.trial_feature USING btree (trial_id, channel_no, feature_id)`

## lab.mv_monthly_throughput

*materialized view.* Sessions, recordings and hours recorded per month and study. Stored: refresh it after loading data.

| column | type | null | default | description |
|---|---|---|---|---|
| `month` | date |  |  |  |
| `study_code` | text |  |  |  |
| `sessions_completed` | bigint |  |  |  |
| `sessions_missed` | bigint |  |  |  |
| `recordings` | integer |  |  |  |
| `hours_recorded` | numeric |  |  |  |

Indexes:

- `mv_monthly_throughput_key`: `CREATE UNIQUE INDEX mv_monthly_throughput_key ON lab.mv_monthly_throughput USING btree (month, study_code)`

## lab.v_device_status

*view.* One row per device: calibration_status is retired, never_calibrated, overdue, due_soon (within 14 days) or ok, as of lab.reference_date().

| column | type | null | default | description |
|---|---|---|---|---|
| `device_id` | integer |  |  |  |
| `kind` | lab.device_kind |  |  |  |
| `model` | text |  |  |  |
| `serial_no` | text |  |  |  |
| `home_room` | text |  |  |  |
| `last_passed_on` | date |  |  |  |
| `valid_until` | date |  |  |  |
| `calibration_status` | text |  |  |  |
| `days_overdue` | integer |  |  |  |

## lab.v_participant_progress

*view.* One row per enrollment: visits completed, scheduled and missed, and a progress label (not_started, in_progress, finished, withdrawn).

| column | type | null | default | description |
|---|---|---|---|---|
| `study_id` | integer |  |  |  |
| `study_code` | text |  |  |  |
| `participant_id` | integer |  |  |  |
| `participant_code` | text |  |  |  |
| `group_label` | text |  |  |  |
| `enrolled_on` | date |  |  |  |
| `planned_visits` | smallint |  |  |  |
| `completed_visits` | bigint |  |  |  |
| `scheduled_visits` | bigint |  |  |  |
| `missed_visits` | bigint |  |  |  |
| `last_completed_at` | timestamp with time zone |  |  |  |
| `progress` | text |  |  |  |

## lab.v_recording_summary

*view.* One row per recording with its number of trials, how many are valid, and the percentage.

| column | type | null | default | description |
|---|---|---|---|---|
| `recording_id` | bigint |  |  |  |
| `session_id` | bigint |  |  |  |
| `modality` | lab.modality |  |  |  |
| `recorded_at` | timestamp with time zone |  |  |  |
| `duration_s` | numeric(8,2) |  |  |  |
| `qc` | lab.qc_status |  |  |  |
| `n_trials` | bigint |  |  |  |
| `n_valid_trials` | bigint |  |  |  |
| `valid_pct` | numeric |  |  |  |

## lab.v_session_detail

*view.* One row per session with the names of its study, participant, group and researcher.

| column | type | null | default | description |
|---|---|---|---|---|
| `session_id` | bigint |  |  |  |
| `study_code` | text |  |  |  |
| `participant_code` | text |  |  |  |
| `group_label` | text |  |  |  |
| `visit_no` | smallint |  |  |  |
| `researcher` | text |  |  |  |
| `room` | text |  |  |  |
| `starts_at` | timestamp with time zone |  |  |  |
| `ends_at` | timestamp with time zone |  |  |  |
| `duration_min` | integer |  |  |  |
| `status` | lab.session_status |  |  |  |

## bi.dim_date

*view.* Calendar, one row per day 2023-2028 (generated), for time intelligence in BI tools.

| column | type | null | default | description |
|---|---|---|---|---|
| `date_key` | date |  |  |  |
| `year` | integer |  |  |  |
| `quarter` | integer |  |  |  |
| `month_no` | integer |  |  |  |
| `year_month` | text |  |  |  |
| `month_name` | text |  |  |  |
| `month_start` | date |  |  |  |
| `iso_weekday` | integer |  |  |  |
| `weekday_name` | text |  |  |  |
| `is_weekend` | boolean |  |  |  |

## bi.dim_device

*view.* Dimension: devices.

| column | type | null | default | description |
|---|---|---|---|---|
| `device_key` | integer |  |  |  |
| `kind` | text |  |  |  |
| `model` | text |  |  |  |
| `serial_no` | text |  |  |  |
| `home_room` | text |  |  |  |
| `acquired_on` | date |  |  |  |
| `retired_on` | date |  |  |  |

## bi.dim_participant

*view.* Dimension: participants (pseudonymised).

| column | type | null | default | description |
|---|---|---|---|---|
| `participant_key` | integer |  |  |  |
| `participant_code` | text |  |  |  |
| `birth_year` | smallint |  |  |  |
| `sex` | character(1) |  |  |  |
| `dominant_hand` | lab.hand |  |  |  |
| `consent_signed_on` | date |  |  |  |
| `withdrawn_on` | date |  |  |  |
| `is_withdrawn` | boolean |  |  |  |

## bi.dim_researcher

*view.* Dimension: researchers.

| column | type | null | default | description |
|---|---|---|---|---|
| `researcher_key` | integer |  |  |  |
| `full_name` | text |  |  |  |
| `role` | text |  |  |  |
| `hired_on` | date |  |  |  |
| `left_on` | date |  |  |  |

## bi.dim_study

*view.* Dimension: studies.

| column | type | null | default | description |
|---|---|---|---|---|
| `study_key` | integer |  |  |  |
| `study_code` | text |  |  |  |
| `title` | text |  |  |  |
| `started_on` | date |  |  |  |
| `ended_on` | date |  |  |  |
| `planned_visits` | smallint |  |  |  |
| `target_n` | integer |  |  |  |

## bi.fact_recording

*view.* Fact: one row per recording, with its size and trial counts.

| column | type | null | default | description |
|---|---|---|---|---|
| `recording_key` | bigint |  |  |  |
| `session_key` | bigint |  |  |  |
| `date_key` | date |  |  |  |
| `device_key` | integer |  |  |  |
| `modality` | text |  |  |  |
| `sampling_rate_hz` | integer |  |  |  |
| `n_channels` | smallint |  |  |  |
| `duration_s` | numeric(8,2) |  |  |  |
| `size_mb` | numeric |  |  |  |
| `qc` | text |  |  |  |
| `n_trials` | bigint |  |  |  |
| `n_valid_trials` | bigint |  |  |  |
| `device_calibrated` | boolean |  |  | true when some passed calibration of the device covered the day of the recording (lab calendar day); false is a data-quality finding, see query 04. |

## bi.fact_session

*view.* Fact: one row per session, with its local date and the recordings it produced.

| column | type | null | default | description |
|---|---|---|---|---|
| `session_key` | bigint |  |  |  |
| `date_key` | date |  |  |  |
| `study_key` | integer |  |  |  |
| `participant_key` | integer |  |  |  |
| `researcher_key` | integer |  |  |  |
| `group_label` | text |  |  |  |
| `visit_no` | smallint |  |  |  |
| `room` | text |  |  |  |
| `status` | text |  |  |  |
| `duration_min` | integer |  |  |  |
| `starts_local` | timestamp without time zone |  |  |  |
| `n_recordings` | bigint |  |  |  |
| `hours_recorded` | numeric |  |  |  |

## bi.fact_trial

*view.* Fact: one row per trial, with the features of its modality as columns (NULL for a trial of another modality).

| column | type | null | default | description |
|---|---|---|---|---|
| `trial_key` | bigint |  |  |  |
| `recording_key` | bigint |  |  |  |
| `session_key` | bigint |  |  |  |
| `date_key` | date |  |  |  |
| `modality` | text |  |  |  |
| `condition` | text |  |  |  |
| `trial_no` | integer |  |  |  |
| `onset_s` | numeric(8,3) |  |  |  |
| `duration_s` | numeric(6,3) |  |  |  |
| `valid` | boolean |  |  |  |
| `reject_reason` | text |  |  |  |
| `rms_mean_uv` | numeric |  |  | EMG: root mean square amplitude, in microvolts, averaged over the channels. |
| `peak_force_n` | numeric |  |  | Force: the highest force of the trial, in newtons. |
| `force_cv_pct` | numeric |  |  | Force: coefficient of variation of the force in the hold phase, in percent. Lower is steadier. |
| `mnf_hz` | numeric |  |  | EMG: mean frequency of the power spectrum, in hertz, averaged over the channels. |
| `mdf_hz` | numeric |  |  | EMG: median frequency of the power spectrum, in hertz, averaged over the channels. |
| `alpha_power_uv2` | numeric |  |  | EEG: band power at 8 to 13 Hz, in microvolts squared, averaged over the channels. |
