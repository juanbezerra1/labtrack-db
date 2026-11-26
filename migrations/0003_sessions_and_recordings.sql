-- 0003: sessions, recordings, channels and trials. The tables that grow.
--
-- Three ideas to look for in this file:
--   1. A composite foreign key: a session can only exist for a participant who is ENROLLED in that
--      study, and a recording can only use a device that was booked for ITS session.
--   2. An exclusion constraint: two active sessions cannot overlap in the same room.
--   3. A trigger for the rules a CHECK cannot express because they look at other tables.

CREATE TABLE lab.session (
    session_id      bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    study_id        integer     NOT NULL,
    participant_id  integer     NOT NULL,
    researcher_id   integer     NOT NULL REFERENCES lab.researcher (researcher_id),
    visit_no        smallint    NOT NULL,
    room            text        NOT NULL,
    starts_at       timestamptz NOT NULL,
    ends_at         timestamptz NOT NULL,
    status          lab.session_status NOT NULL DEFAULT 'scheduled',
    notes           jsonb       NOT NULL DEFAULT '{}'::jsonb,
    -- Generated columns: computed by the database from other columns, stored, never written by hand.
    during          tstzrange   GENERATED ALWAYS AS (tstzrange(starts_at, ends_at)) STORED,
    duration_min    integer     GENERATED ALWAYS AS ((extract(epoch FROM (ends_at - starts_at)) / 60)::integer) STORED,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    -- (study_id, participant_id) must exist in enrollment: no sessions for people who are not enrolled.
    CONSTRAINT session_enrollment_fk FOREIGN KEY (study_id, participant_id)
        REFERENCES lab.enrollment (study_id, participant_id),
    CONSTRAINT session_visit_unique  UNIQUE (study_id, participant_id, visit_no),
    CONSTRAINT session_visit_range   CHECK (visit_no BETWEEN 1 AND 20),
    CONSTRAINT session_room_format   CHECK (room ~ '^R[0-9]{2}$'),
    CONSTRAINT session_times_ordered CHECK (ends_at > starts_at),
    CONSTRAINT session_max_length    CHECK (ends_at - starts_at <= interval '6 hours'),
    CONSTRAINT session_notes_object  CHECK (jsonb_typeof(notes) = 'object'),
    -- A room hosts one active session at a time. Cancelled and no-show sessions do not block it.
    CONSTRAINT session_room_no_overlap EXCLUDE USING gist (room WITH =, during WITH &&)
        WHERE (status IN ('scheduled', 'completed'))
);
COMMENT ON TABLE  lab.session IS 'One visit of one participant to the lab, in one room, run by one researcher.';
COMMENT ON COLUMN lab.session.during IS 'Generated: the time range [starts_at, ends_at). The exclusion constraint compares these.';
COMMENT ON COLUMN lab.session.notes  IS 'Free-form protocol notes as a JSON object (protocol version, room temperature, issues...).';
CREATE INDEX session_participant_idx ON lab.session (participant_id, starts_at);
CREATE INDEX session_researcher_idx  ON lab.session (researcher_id);
CREATE INDEX session_starts_at_idx   ON lab.session (starts_at);
CREATE TRIGGER session_set_updated_at BEFORE UPDATE ON lab.session
    FOR EACH ROW EXECUTE FUNCTION lab.set_updated_at();

-- Rules that depend on other tables. A CHECK constraint cannot read another table, a trigger can.
-- Each rule raises a check_violation (SQLSTATE 23514) that names the constraint it stands for.
CREATE FUNCTION lab.session_rules() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    day        date := (NEW.starts_at AT TIME ZONE 'America/Sao_Paulo')::date;
    consent    date;
    withdrawn  date;
    enrolled   date;
    s_start    date;
    s_end      date;
BEGIN
    -- Only sessions that really happen (or will) are held to the rules; a cancelled one is just a record.
    IF NEW.status NOT IN ('scheduled', 'completed') THEN
        RETURN NEW;
    END IF;

    SELECT p.consent_signed_on, p.withdrawn_on INTO consent, withdrawn
    FROM lab.participant AS p WHERE p.participant_id = NEW.participant_id;
    SELECT e.enrolled_on INTO enrolled
    FROM lab.enrollment AS e WHERE e.study_id = NEW.study_id AND e.participant_id = NEW.participant_id;
    SELECT st.started_on, st.ended_on INTO s_start, s_end
    FROM lab.study AS st WHERE st.study_id = NEW.study_id;

    IF day < consent THEN
        RAISE EXCEPTION 'session on % is before the participant signed consent (%)', day, consent
            USING ERRCODE = 'check_violation', CONSTRAINT = 'session_before_consent';
    END IF;
    IF withdrawn IS NOT NULL AND day > withdrawn THEN
        RAISE EXCEPTION 'session on % is after the participant withdrew (%)', day, withdrawn
            USING ERRCODE = 'check_violation', CONSTRAINT = 'session_after_withdrawal';
    END IF;
    IF day < enrolled THEN
        RAISE EXCEPTION 'session on % is before the enrollment date (%)', day, enrolled
            USING ERRCODE = 'check_violation', CONSTRAINT = 'session_before_enrollment';
    END IF;
    IF day < s_start OR (s_end IS NOT NULL AND day > s_end) THEN
        RAISE EXCEPTION 'session on % is outside the study period (% to %)', day, s_start, coalesce(s_end::text, 'open')
            USING ERRCODE = 'check_violation', CONSTRAINT = 'session_outside_study';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER session_rules BEFORE INSERT OR UPDATE OF starts_at, participant_id, study_id, status
    ON lab.session FOR EACH ROW EXECUTE FUNCTION lab.session_rules();

-- Which devices a session used (many-to-many).
CREATE TABLE lab.session_device (
    session_id  bigint  NOT NULL REFERENCES lab.session (session_id) ON DELETE CASCADE,
    device_id   integer NOT NULL REFERENCES lab.device (device_id),
    PRIMARY KEY (session_id, device_id)
);
COMMENT ON TABLE lab.session_device IS
    'The devices booked for a session. A recording may only use a device listed here (composite foreign key).';
CREATE INDEX session_device_device_idx ON lab.session_device (device_id);

CREATE TABLE lab.recording (
    recording_id    bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id      bigint      NOT NULL,
    device_id       integer     NOT NULL,
    modality        lab.modality NOT NULL,
    block_no        smallint    NOT NULL DEFAULT 1,
    sampling_rate_hz integer    NOT NULL,
    n_channels      smallint    NOT NULL,
    recorded_at     timestamptz NOT NULL,
    duration_s      numeric(8,2) NOT NULL,
    size_bytes      bigint      NOT NULL,
    sha256          char(64)    NOT NULL UNIQUE,
    storage_uri     text        NOT NULL,
    qc              lab.qc_status NOT NULL DEFAULT 'pending',
    -- The device must be one of the devices booked for THIS session.
    CONSTRAINT recording_session_device_fk FOREIGN KEY (session_id, device_id)
        REFERENCES lab.session_device (session_id, device_id),
    CONSTRAINT recording_block_unique   UNIQUE (session_id, modality, block_no),
    CONSTRAINT recording_rate_range     CHECK (sampling_rate_hz BETWEEN 1 AND 100000),
    CONSTRAINT recording_channels_range CHECK (n_channels BETWEEN 1 AND 256),
    CONSTRAINT recording_duration_positive CHECK (duration_s > 0),
    CONSTRAINT recording_size_nonnegative  CHECK (size_bytes >= 0),
    CONSTRAINT recording_sha256_format  CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT recording_uri_scheme     CHECK (storage_uri ~ '^(s3|file)://')
);
COMMENT ON TABLE  lab.recording IS 'A file of raw signal. The signal itself stays in storage; the database keeps what you need to find and trust it.';
COMMENT ON COLUMN lab.recording.sha256 IS 'Hash of the file. UNIQUE, so the same recording cannot be registered twice.';
CREATE INDEX recording_device_idx ON lab.recording (device_id);

CREATE TABLE lab.channel (
    recording_id    bigint   NOT NULL REFERENCES lab.recording (recording_id) ON DELETE CASCADE,
    channel_no      smallint NOT NULL,
    label           text     NOT NULL,
    unit            text     NOT NULL,
    PRIMARY KEY (recording_id, channel_no),
    CONSTRAINT channel_no_positive CHECK (channel_no >= 1),
    CONSTRAINT channel_unit_values CHECK (unit IN ('uV', 'mV', 'V', 'N'))
);

COMMENT ON TABLE lab.channel IS 'The channels of a recording: which electrode or sensor each column of the signal came from.';
COMMENT ON COLUMN lab.recording.qc IS 'Quality-control state: pending until someone reviews the recording, then passed, flagged (usable with care) or rejected.';
COMMENT ON COLUMN lab.session.status IS 'scheduled (in the future), completed, cancelled or no_show. Only scheduled and completed sessions hold a room.';

CREATE TABLE lab.trial (
    trial_id        bigint   GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recording_id    bigint   NOT NULL REFERENCES lab.recording (recording_id) ON DELETE CASCADE,
    trial_no        integer  NOT NULL,
    condition       text     NOT NULL,
    onset_s         numeric(8,3) NOT NULL,
    duration_s      numeric(6,3) NOT NULL,
    valid           boolean  NOT NULL DEFAULT true,
    reject_reason   text,
    CONSTRAINT trial_number_unique   UNIQUE (recording_id, trial_no),
    CONSTRAINT trial_number_positive CHECK (trial_no >= 1),
    CONSTRAINT trial_onset_nonnegative CHECK (onset_s >= 0),
    CONSTRAINT trial_duration_positive CHECK (duration_s > 0),
    -- Valid trials have no reason; rejected trials must say why.
    CONSTRAINT trial_reason_iff_rejected CHECK ((valid AND reject_reason IS NULL) OR (NOT valid AND reject_reason IS NOT NULL))
);
COMMENT ON TABLE lab.trial IS 'One repetition inside a recording (for example, one 6 s contraction at 20% of maximum).';
COMMENT ON COLUMN lab.trial.condition IS 'The experimental condition of the trial, such as hold_40_fb (40% of maximum force, feedback on).';
COMMENT ON COLUMN lab.trial.valid IS 'False when the trial was thrown out in review; reject_reason then says why.';

-- Column comments (they feed docs/data-dictionary.md, which is generated from the catalog).
COMMENT ON COLUMN lab.session.session_id IS 'Surrogate key, assigned by the database.';
COMMENT ON COLUMN lab.session.study_id IS 'The study; with participant_id it must exist in lab.enrollment.';
COMMENT ON COLUMN lab.session.participant_id IS 'The participant.';
COMMENT ON COLUMN lab.session.researcher_id IS 'Who ran the session.';
COMMENT ON COLUMN lab.session.visit_no IS '1, 2, 3... in the order of the participant''s visits; make-up visits continue the numbering.';
COMMENT ON COLUMN lab.session.room IS 'Room code such as R03.';
COMMENT ON COLUMN lab.session.starts_at IS 'Start of the session (an absolute moment; the lab''s local time is America/Sao_Paulo).';
COMMENT ON COLUMN lab.session.ends_at IS 'End of the session; at most six hours after the start.';
COMMENT ON COLUMN lab.session.duration_min IS 'Generated: the length in whole minutes.';
COMMENT ON COLUMN lab.session.created_at IS 'When the row was inserted.';
COMMENT ON COLUMN lab.session.updated_at IS 'When the row was last changed (maintained by a trigger).';
COMMENT ON COLUMN lab.session_device.session_id IS 'The session.';
COMMENT ON COLUMN lab.session_device.device_id IS 'A device booked for it.';
COMMENT ON COLUMN lab.recording.recording_id IS 'Surrogate key, assigned by the database.';
COMMENT ON COLUMN lab.recording.session_id IS 'The session in which the signal was recorded.';
COMMENT ON COLUMN lab.recording.device_id IS 'The device that recorded it; must be one booked for the session.';
COMMENT ON COLUMN lab.recording.modality IS 'emg, eeg or force.';
COMMENT ON COLUMN lab.recording.block_no IS 'Which block of the session, when a modality is recorded more than once (before and after a task, say).';
COMMENT ON COLUMN lab.recording.sampling_rate_hz IS 'Samples per second, per channel.';
COMMENT ON COLUMN lab.recording.n_channels IS 'How many channels the file has; lab.channel has one row for each.';
COMMENT ON COLUMN lab.recording.recorded_at IS 'When the recording started.';
COMMENT ON COLUMN lab.recording.duration_s IS 'Length of the recording in seconds.';
COMMENT ON COLUMN lab.recording.size_bytes IS 'Size of the file.';
COMMENT ON COLUMN lab.recording.storage_uri IS 'Where the file is: s3://bucket/path or file:///path.';
COMMENT ON COLUMN lab.channel.recording_id IS 'The recording.';
COMMENT ON COLUMN lab.channel.channel_no IS '1 to n_channels: the column of the signal this row describes.';
COMMENT ON COLUMN lab.channel.label IS 'Electrode or sensor name, such as biceps or Cz.';
COMMENT ON COLUMN lab.channel.unit IS 'Unit of the signal: uV, mV, V or N.';
COMMENT ON COLUMN lab.trial.trial_id IS 'Surrogate key, assigned by the database.';
COMMENT ON COLUMN lab.trial.recording_id IS 'The recording the trial belongs to.';
COMMENT ON COLUMN lab.trial.trial_no IS '1, 2, 3... within the recording.';
COMMENT ON COLUMN lab.trial.onset_s IS 'Seconds from the start of the recording to the start of the trial.';
COMMENT ON COLUMN lab.trial.duration_s IS 'Length of the trial in seconds.';
COMMENT ON COLUMN lab.trial.reject_reason IS 'Why a rejected trial was thrown out; NULL for valid trials (enforced).';
