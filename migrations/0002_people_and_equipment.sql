-- 0002: studies, people and equipment. The tables that change slowly.
--
-- Reading guide for the constraints used below:
--   PRIMARY KEY   identifies a row; UNIQUE says "no two rows may share this value".
--   FOREIGN KEY   a value must exist in the table it points to (ON DELETE RESTRICT is the default:
--                 you cannot delete a study that still has participants).
--   CHECK         a rule about the row itself. Write them as close to the column as you can.
--   NOT NULL      the cheapest and most useful constraint of all: say it whenever it is true.

CREATE TABLE lab.study (
    study_id        integer     GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code            text        NOT NULL UNIQUE,
    title           text        NOT NULL,
    started_on      date        NOT NULL,
    ended_on        date,
    planned_visits  smallint    NOT NULL DEFAULT 4,
    target_n        integer     NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT study_code_format   CHECK (code ~ '^[A-Z]{2,6}-[0-9]{2}$'),
    CONSTRAINT study_title_length  CHECK (length(title) BETWEEN 5 AND 200),
    CONSTRAINT study_dates_ordered CHECK (ended_on IS NULL OR ended_on >= started_on),
    CONSTRAINT study_visits_range  CHECK (planned_visits BETWEEN 1 AND 20),
    CONSTRAINT study_target_positive CHECK (target_n > 0)
);
COMMENT ON TABLE  lab.study IS 'A study (protocol): a question, a period, a planned number of visits per participant.';
COMMENT ON COLUMN lab.study.code IS 'Short stable code such as FFB-01 (letters, a dash, two digits).';
COMMENT ON COLUMN lab.study.planned_visits IS 'How many sessions each participant is supposed to attend.';
CREATE TRIGGER study_set_updated_at BEFORE UPDATE ON lab.study
    FOR EACH ROW EXECUTE FUNCTION lab.set_updated_at();

CREATE TABLE lab.researcher (
    researcher_id   integer     GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    full_name       text        NOT NULL,
    role            lab.researcher_role NOT NULL,
    email           text        NOT NULL UNIQUE,
    hired_on        date        NOT NULL,
    left_on         date,
    CONSTRAINT researcher_name_length CHECK (length(btrim(full_name)) >= 3),
    CONSTRAINT researcher_email_shape CHECK (email ~* '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'),
    CONSTRAINT researcher_dates_ordered CHECK (left_on IS NULL OR left_on > hired_on)
);
COMMENT ON TABLE lab.researcher IS 'Lab staff. The data in this repository is synthetic: names and e-mails are invented.';

CREATE TABLE lab.participant (
    participant_id  integer     GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code            text        NOT NULL UNIQUE,
    birth_year      smallint    NOT NULL,
    sex             char(1)     NOT NULL,
    dominant_hand   lab.hand    NOT NULL,
    consent_signed_on date      NOT NULL,
    withdrawn_on    date,
    CONSTRAINT participant_code_format CHECK (code ~ '^P[0-9]{4,6}$'),
    CONSTRAINT participant_birth_range CHECK (birth_year BETWEEN 1930 AND 2010),
    CONSTRAINT participant_sex_values  CHECK (sex IN ('F', 'M')),
    CONSTRAINT participant_withdrawal_ordered CHECK (withdrawn_on IS NULL OR withdrawn_on >= consent_signed_on)
);
COMMENT ON TABLE lab.participant IS
    'One row per person. Pseudonymised by design: a code, a birth year and nothing that identifies anyone.';
COMMENT ON COLUMN lab.participant.consent_signed_on IS 'No session may start before this day (enforced by a trigger).';

-- Many-to-many between studies and participants, with attributes of the relationship itself.
CREATE TABLE lab.enrollment (
    study_id        integer     NOT NULL REFERENCES lab.study (study_id),
    participant_id  integer     NOT NULL REFERENCES lab.participant (participant_id),
    group_label     text        NOT NULL,
    enrolled_on     date        NOT NULL,
    PRIMARY KEY (study_id, participant_id),
    CONSTRAINT enrollment_group_values CHECK (group_label IN ('control', 'intervention'))
);
COMMENT ON TABLE lab.enrollment IS
    'Which participant takes part in which study, and in which group. The primary key is the pair, so nobody is enrolled twice in a study.';
COMMENT ON COLUMN lab.enrollment.group_label IS 'control or intervention. Assigned at enrollment and never changed.';
-- PostgreSQL indexes the PRIMARY KEY and UNIQUE columns, but NOT the referencing side of a foreign
-- key. This index serves "which studies is this participant in?" and the cascade checks.
CREATE INDEX enrollment_participant_idx ON lab.enrollment (participant_id);

CREATE TABLE lab.device (
    device_id       integer     GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind            lab.device_kind NOT NULL,
    model           text        NOT NULL,
    serial_no       text        NOT NULL UNIQUE,
    home_room       text        NOT NULL,
    acquired_on     date        NOT NULL,
    retired_on      date,
    CONSTRAINT device_room_format    CHECK (home_room ~ '^R[0-9]{2}$'),
    CONSTRAINT device_dates_ordered  CHECK (retired_on IS NULL OR retired_on > acquired_on)
);
COMMENT ON TABLE lab.device IS 'Amplifiers, dynamometers and stimulators. home_room is where the device normally lives.';

CREATE TABLE lab.calibration (
    calibration_id  integer     GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_id       integer     NOT NULL REFERENCES lab.device (device_id),
    performed_on    date        NOT NULL,
    performed_by    integer     NOT NULL REFERENCES lab.researcher (researcher_id),
    passed          boolean     NOT NULL,
    valid_until     date        NOT NULL,
    notes           text,
    UNIQUE (device_id, performed_on),
    CONSTRAINT calibration_dates_ordered CHECK (valid_until > performed_on)
);
COMMENT ON TABLE lab.calibration IS
    'One row per calibration round of a device. A failed round (passed = false) covers nothing and is usually repeated.';
COMMENT ON COLUMN lab.calibration.valid_until IS
    'Last day (exclusive) on which this calibration covers the device. Only counts when passed is true.';
-- No index is needed for "the latest calibration of a device": the UNIQUE (device_id, performed_on)
-- above already is one, and a B-tree can be read backwards, so ORDER BY performed_on DESC LIMIT 1 is
-- an index lookup. (A second index on (device_id, performed_on DESC) would be pure overhead.)
CREATE INDEX calibration_performed_by_idx ON lab.calibration (performed_by);

-- Column comments (they feed docs/data-dictionary.md, which is generated from the catalog).
COMMENT ON COLUMN lab.study.study_id IS 'Surrogate key, assigned by the database.';
COMMENT ON COLUMN lab.study.title IS 'Descriptive title, 5 to 200 characters.';
COMMENT ON COLUMN lab.study.started_on IS 'First day of the study; no session may happen before it.';
COMMENT ON COLUMN lab.study.ended_on IS 'Last day of the study; NULL while it is still open.';
COMMENT ON COLUMN lab.study.target_n IS 'How many participants the study aims to enroll.';
COMMENT ON COLUMN lab.study.created_at IS 'When the row was inserted.';
COMMENT ON COLUMN lab.study.updated_at IS 'When the row was last changed (maintained by a trigger).';
COMMENT ON COLUMN lab.researcher.researcher_id IS 'Surrogate key, assigned by the database.';
COMMENT ON COLUMN lab.researcher.full_name IS 'Invented name (the data in this repository is synthetic).';
COMMENT ON COLUMN lab.researcher.role IS 'pi, postdoc, phd, msc or technician.';
COMMENT ON COLUMN lab.researcher.email IS 'Unique address, also invented: the domain ends in .example, a name reserved for documentation that never resolves.';
COMMENT ON COLUMN lab.researcher.hired_on IS 'First day in the lab.';
COMMENT ON COLUMN lab.researcher.left_on IS 'Day the person left; NULL while still employed.';
COMMENT ON COLUMN lab.participant.participant_id IS 'Surrogate key, assigned by the database.';
COMMENT ON COLUMN lab.participant.code IS 'Pseudonym such as P0042. The link to a real person, if any, lives outside this database.';
COMMENT ON COLUMN lab.participant.birth_year IS 'Year only, never the full date: enough for age analyses, not enough to identify anyone.';
COMMENT ON COLUMN lab.participant.sex IS 'F or M, as recorded for the study.';
COMMENT ON COLUMN lab.participant.dominant_hand IS 'right, left or ambidextrous.';
COMMENT ON COLUMN lab.participant.withdrawn_on IS 'Day the participant withdrew; NULL while still taking part. No active session may be later than this day.';
COMMENT ON COLUMN lab.enrollment.study_id IS 'The study.';
COMMENT ON COLUMN lab.enrollment.participant_id IS 'The participant.';
COMMENT ON COLUMN lab.enrollment.enrolled_on IS 'Day the participant joined the study; no session may be earlier.';
COMMENT ON COLUMN lab.device.device_id IS 'Surrogate key, assigned by the database.';
COMMENT ON COLUMN lab.device.kind IS 'emg_amplifier, eeg_amplifier, dynamometer or stimulator.';
COMMENT ON COLUMN lab.device.model IS 'Model name.';
COMMENT ON COLUMN lab.device.home_room IS 'Room where the device normally lives, such as R03.';
COMMENT ON COLUMN lab.device.serial_no IS 'Manufacturer serial number, unique.';
COMMENT ON COLUMN lab.device.acquired_on IS 'Day the lab got the device.';
COMMENT ON COLUMN lab.device.retired_on IS 'Day it was taken out of service; NULL while in use.';
COMMENT ON COLUMN lab.calibration.calibration_id IS 'Surrogate key, assigned by the database.';
COMMENT ON COLUMN lab.calibration.device_id IS 'The device that was calibrated.';
COMMENT ON COLUMN lab.calibration.performed_on IS 'Day of the calibration round.';
COMMENT ON COLUMN lab.calibration.performed_by IS 'The researcher (a technician, usually) who did it.';
COMMENT ON COLUMN lab.calibration.passed IS 'False when the device was out of tolerance; such a round covers nothing.';
COMMENT ON COLUMN lab.calibration.notes IS 'Free text; filled in when something went wrong.';
