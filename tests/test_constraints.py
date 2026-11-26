"""Every rule the schema enforces, tested by trying to break it.

Part 1 is a table of bad rows: each must be refused, by the named constraint. Part 2 tests the rules
that need a story (double booking, consent dates, cascades, generated columns).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import psycopg
import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from labtrack.db import row, scalar

from .builders import Lab, World, at, violates

Case = tuple[str, Callable[[Lab, World], Any], type[Exception], str | None]


def _recording(**kw: Any) -> Callable[[Lab, World], Any]:
    return lambda lab, w: lab.recording(lab.booked_session(w), w.device, **kw)


def _trial(**kw: Any) -> Callable[[Lab, World], Any]:
    return lambda lab, w: lab.trial(lab.recording(lab.booked_session(w), w.device), **kw)


BAD_ROWS: list[Case] = [
    # ---- study ----
    ("study code lower case", lambda lab, w: lab.study(code="abc-01"), errors.CheckViolation, "study_code_format"),
    ("study code without digits", lambda lab, w: lab.study(code="FFB"), errors.CheckViolation, "study_code_format"),
    ("study title too short", lambda lab, w: lab.study(title="abc"), errors.CheckViolation, "study_title_length"),
    ("study ends before it starts", lambda lab, w: lab.study(started_on="2024-05-01", ended_on="2024-04-01"),
     errors.CheckViolation, "study_dates_ordered"),
    ("study with zero visits", lambda lab, w: lab.study(planned_visits=0), errors.CheckViolation, "study_visits_range"),
    ("study with 21 visits", lambda lab, w: lab.study(planned_visits=21), errors.CheckViolation, "study_visits_range"),
    ("study target of zero", lambda lab, w: lab.study(target_n=0), errors.CheckViolation, "study_target_positive"),
    ("study code taken", lambda lab, w: lab.study(code=scalar(lab.conn, "SELECT code FROM lab.study")),
     errors.UniqueViolation, "study_code_key"),
    # ---- researcher ----
    ("researcher with a blank name", lambda lab, w: lab.researcher(full_name="  a "), errors.CheckViolation,
     "researcher_name_length"),
    ("researcher e-mail without @", lambda lab, w: lab.researcher(email="nobody.lab.example"),
     errors.CheckViolation, "researcher_email_shape"),
    ("researcher leaves the day they arrive", lambda lab, w: lab.researcher(hired_on="2024-01-01", left_on="2024-01-01"),
     errors.CheckViolation, "researcher_dates_ordered"),
    ("researcher e-mail taken", lambda lab, w: lab.researcher(
        email=scalar(lab.conn, "SELECT email FROM lab.researcher")),
     errors.UniqueViolation, "researcher_email_key"),
    ("researcher role not in the enum", lambda lab, w: lab.researcher(role="janitor"),
     errors.InvalidTextRepresentation, None),
    # ---- participant ----
    ("participant code without the P", lambda lab, w: lab.participant(code="X0001"), errors.CheckViolation,
     "participant_code_format"),
    ("participant born in 1900", lambda lab, w: lab.participant(birth_year=1900), errors.CheckViolation,
     "participant_birth_range"),
    ("participant sex other than F or M", lambda lab, w: lab.participant(sex="X"), errors.CheckViolation,
     "participant_sex_values"),
    ("participant withdraws before consenting",
     lambda lab, w: lab.participant(consent_signed_on="2024-03-01", withdrawn_on="2024-02-01"),
     errors.CheckViolation, "participant_withdrawal_ordered"),
    ("participant code taken", lambda lab, w: lab.participant(
        code=scalar(lab.conn, "SELECT code FROM lab.participant")),
     errors.UniqueViolation, "participant_code_key"),
    # ---- enrollment ----
    ("enrollment in an unknown group", lambda lab, w: lab.enrollment(w.study, lab.participant(), group_label="placebo"),
     errors.CheckViolation, "enrollment_group_values"),
    ("enrollment of a participant who does not exist", lambda lab, w: lab.enrollment(w.study, 999_999),
     errors.ForeignKeyViolation, "enrollment_participant_id_fkey"),
    ("the same enrollment twice", lambda lab, w: lab.enrollment(w.study, w.participant),
     errors.UniqueViolation, "enrollment_pkey"),
    # ---- device and calibration ----
    ("device room not like R01", lambda lab, w: lab.device(home_room="room 1"), errors.CheckViolation,
     "device_room_format"),
    ("device retired before it was acquired", lambda lab, w: lab.device(acquired_on="2024-01-01", retired_on="2023-01-01"),
     errors.CheckViolation, "device_dates_ordered"),
    ("device serial number taken", lambda lab, w: lab.device(
        serial_no=scalar(lab.conn, "SELECT serial_no FROM lab.device")),
     errors.UniqueViolation, "device_serial_no_key"),
    ("calibration that expires before it happens",
     lambda lab, w: lab.calibration(w.device, w.researcher, performed_on="2024-03-01", valid_until="2024-03-01"),
     errors.CheckViolation, "calibration_dates_ordered"),
    ("two calibrations of one device on one day",
     lambda lab, w: (lab.calibration(w.device, w.researcher), lab.calibration(w.device, w.researcher)),
     errors.UniqueViolation, "calibration_device_id_performed_on_key"),
    # ---- session ----
    ("session for a participant who is not enrolled in the study",
     lambda lab, w: lab.session(w.study, lab.participant(), w.researcher),
     errors.ForeignKeyViolation, "session_enrollment_fk"),
    ("the same visit number twice",
     lambda lab, w: (lab.session(w.study, w.participant, w.researcher),
                     lab.session(w.study, w.participant, w.researcher, starts_at=at("2024-02-06"), ends_at=at("2024-02-06", "10:00"))),
     errors.UniqueViolation, "session_visit_unique"),
    ("visit number zero", lambda lab, w: lab.session(w.study, w.participant, w.researcher, visit_no=0),
     errors.CheckViolation, "session_visit_range"),
    ("room not like R01", lambda lab, w: lab.session(w.study, w.participant, w.researcher, room="lab 1"),
     errors.CheckViolation, "session_room_format"),
    ("session of zero length",
     lambda lab, w: lab.session(w.study, w.participant, w.researcher, ends_at=at("2024-02-05")),
     errors.CheckViolation, "session_times_ordered"),
    ("session longer than six hours",
     lambda lab, w: lab.session(w.study, w.participant, w.researcher, ends_at=at("2024-02-05", "15:30")),
     errors.CheckViolation, "session_max_length"),
    ("notes that are not a JSON object",
     lambda lab, w: lab.session(w.study, w.participant, w.researcher, notes=Jsonb([1, 2])),
     errors.CheckViolation, "session_notes_object"),
    ("protocol version in the wrong format",
     lambda lab, w: lab.session(w.study, w.participant, w.researcher, protocol_version="two"),
     errors.CheckViolation, "session_protocol_format"),
    ("session without a protocol version",
     lambda lab, w: lab.session(w.study, w.participant, w.researcher, protocol_version=None),
     errors.NotNullViolation, None),
    # ---- recording ----
    ("recording with a device that was not booked for the session",
     lambda lab, w: lab.recording(lab.session(w.study, w.participant, w.researcher), lab.device()),
     errors.ForeignKeyViolation, "recording_session_device_fk"),
    ("the same block recorded twice", lambda lab, w: (lambda s: (lab.recording(s, w.device), lab.recording(s, w.device)))(lab.booked_session(w)),
     errors.UniqueViolation, "recording_block_unique"),
    ("sampling rate of zero", _recording(sampling_rate_hz=0), errors.CheckViolation, "recording_rate_range"),
    ("no channels", _recording(n_channels=0), errors.CheckViolation, "recording_channels_range"),
    ("recording of zero seconds", _recording(duration_s=0), errors.CheckViolation, "recording_duration_positive"),
    ("negative file size", _recording(size_bytes=-1), errors.CheckViolation, "recording_size_nonnegative"),
    ("hash that is not hex", _recording(sha256="z" * 64), errors.CheckViolation, "recording_sha256_format"),
    ("file location that is not s3:// or file://", _recording(storage_uri="http://example.org/x.edf"),
     errors.CheckViolation, "recording_uri_scheme"),
    ("the same file registered twice",
     lambda lab, w: (lambda s: (lab.recording(s, w.device, sha256="a" * 64), lab.recording(s, w.device, block_no=2, sha256="a" * 64)))(lab.booked_session(w)),
     errors.UniqueViolation, "recording_sha256_key"),
    # ---- trial ----
    ("trial number zero", _trial(trial_no=0), errors.CheckViolation, "trial_number_positive"),
    ("trial that starts before the recording", _trial(onset_s=-1), errors.CheckViolation, "trial_onset_nonnegative"),
    ("trial of zero seconds", _trial(duration_s=0), errors.CheckViolation, "trial_duration_positive"),
    ("rejected trial without a reason", _trial(valid=False, reject_reason=None), errors.CheckViolation,
     "trial_reason_iff_rejected"),
    ("valid trial with a rejection reason", _trial(valid=True, reject_reason="movement_artifact"),
     errors.CheckViolation, "trial_reason_iff_rejected"),
]


@pytest.mark.parametrize("label, build, exc_type, constraint", BAD_ROWS, ids=[c[0] for c in BAD_ROWS])
def test_bad_row_is_refused(conn: psycopg.Connection, label: str, build: Callable[[Lab, World], Any],
                            exc_type: type[Exception], constraint: str | None) -> None:
    lab = Lab(conn)
    world = lab.world()
    with violates(conn, exc_type, constraint):
        build(lab, world)


def test_every_named_constraint_is_exercised(conn: psycopg.Connection) -> None:
    """If someone adds a CHECK constraint and forgets to test it, this fails and names it."""
    exercised = {c[3] for c in BAD_ROWS if c[3]}
    # these need a story and are tested below, or protect the long table and are tested in the next block
    tested_elsewhere = {
        "session_room_no_overlap", "session_before_consent", "session_after_withdrawal", "session_before_enrollment",
        "session_outside_study", "trial_number_unique", "channel_no_positive", "channel_unit_values",
        "trial_feature_channel_positive", "trial_feature_finite", "recording_session_device_fk",
        "feature_def_modality_name_key",
    }
    declared = {r[0] for r in conn.execute(
        """SELECT conname FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace
           WHERE n.nspname = 'lab' AND c.contype IN ('c', 'u', 'x') AND c.conname NOT LIKE '%_pkey'""")}
    missing = sorted(declared - exercised - tested_elsewhere)
    assert not missing, f"constraints with no test: {missing}"


# ----------------------------------------------------------------------------------------------
# Rules that need a story
# ----------------------------------------------------------------------------------------------
def test_two_sessions_cannot_share_a_room_at_the_same_time(conn: psycopg.Connection) -> None:
    lab = Lab(conn)
    w = lab.world()
    other = lab.participant()
    lab.enrollment(w.study, other)
    lab.session(w.study, w.participant, w.researcher, starts_at=at("2024-02-05", "09:00"), ends_at=at("2024-02-05", "10:30"))
    with violates(conn, errors.ExclusionViolation, "session_room_no_overlap"):
        lab.session(w.study, other, w.researcher, starts_at=at("2024-02-05", "10:00"), ends_at=at("2024-02-05", "11:00"))


def test_back_to_back_sessions_in_one_room_are_fine(conn: psycopg.Connection) -> None:
    """The range [start, end) leaves the end out, so a session may start the minute the previous one ends."""
    lab = Lab(conn)
    w = lab.world()
    other = lab.participant()
    lab.enrollment(w.study, other)
    lab.session(w.study, w.participant, w.researcher, starts_at=at("2024-02-05", "09:00"), ends_at=at("2024-02-05", "10:00"))
    lab.session(w.study, other, w.researcher, starts_at=at("2024-02-05", "10:00"), ends_at=at("2024-02-05", "11:00"))


def test_overlap_in_different_rooms_is_fine(conn: psycopg.Connection) -> None:
    lab = Lab(conn)
    w = lab.world()
    other = lab.participant()
    lab.enrollment(w.study, other)
    lab.session(w.study, w.participant, w.researcher, room="R01")
    lab.session(w.study, other, w.researcher, room="R02")


def test_a_cancelled_session_does_not_hold_the_room(conn: psycopg.Connection) -> None:
    lab = Lab(conn)
    w = lab.world()
    other = lab.participant()
    lab.enrollment(w.study, other)
    lab.session(w.study, w.participant, w.researcher, status="cancelled")
    lab.session(w.study, other, w.researcher, status="scheduled")  # same room, same time: allowed


def test_reviving_a_cancelled_session_checks_the_room_again(conn: psycopg.Connection) -> None:
    lab = Lab(conn)
    w = lab.world()
    other = lab.participant()
    lab.enrollment(w.study, other)
    old = lab.session(w.study, w.participant, w.researcher, status="cancelled")
    lab.session(w.study, other, w.researcher, status="scheduled")
    with violates(conn, errors.ExclusionViolation, "session_room_no_overlap"):
        conn.execute("UPDATE lab.session SET status = 'scheduled' WHERE session_id = %s", (old,))


def test_session_times_must_be_in_order_even_when_reversed(conn: psycopg.Connection) -> None:
    """A reversed range is refused too. (The generated range column is computed before the CHECK constraints
    run, so PostgreSQL's own range error may fire first; either way the row never gets in.)"""
    lab = Lab(conn)
    w = lab.world()
    with violates(conn, (errors.CheckViolation, errors.DataException)):  # type: ignore[arg-type]
        lab.session(w.study, w.participant, w.researcher, starts_at=at("2024-02-05", "10:00"), ends_at=at("2024-02-05", "09:00"))


@pytest.mark.parametrize(
    "overrides, constraint",
    [
        (dict(starts_at=at("2024-01-01", "09:00"), ends_at=at("2024-01-01", "10:00")), "session_before_consent"),
        (dict(starts_at=at("2024-01-05", "09:00"), ends_at=at("2024-01-05", "10:00")), "session_before_enrollment"),
        (dict(starts_at=at("2023-12-30", "09:00"), ends_at=at("2023-12-30", "10:00")), "session_before_consent"),
        (dict(starts_at=at("2025-06-01", "09:00"), ends_at=at("2025-06-01", "10:00")), "session_outside_study"),
    ],
    ids=["before consent", "before enrollment", "before everything", "after the study ended"],
)
def test_session_date_rules(conn: psycopg.Connection, overrides: dict[str, Any], constraint: str) -> None:
    lab = Lab(conn)
    study = lab.study(started_on="2024-01-01", ended_on="2025-01-01")
    researcher = lab.researcher()
    participant = lab.participant(consent_signed_on="2024-01-02")
    lab.enrollment(study, participant, enrolled_on="2024-01-10")
    with violates(conn, errors.CheckViolation, constraint):
        lab.session(study, participant, researcher, **overrides)


def test_session_after_withdrawal_is_refused_but_a_cancelled_one_is_only_a_record(conn: psycopg.Connection) -> None:
    lab = Lab(conn)
    w = lab.world()
    conn.execute("UPDATE lab.participant SET withdrawn_on = '2024-02-01' WHERE participant_id = %s", (w.participant,))
    with violates(conn, errors.CheckViolation, "session_after_withdrawal"):
        lab.session(w.study, w.participant, w.researcher)
    lab.session(w.study, w.participant, w.researcher, status="cancelled")  # no error


def test_the_session_day_is_the_labs_local_day(conn: psycopg.Connection) -> None:
    """22:30 in Sao Paulo on Feb 5th is already Feb 6th in UTC: the rules must use the local day."""
    lab = Lab(conn)
    study = lab.study(started_on="2024-01-01", ended_on="2024-02-05")
    researcher = lab.researcher()
    participant = lab.participant()
    lab.enrollment(study, participant)
    lab.session(study, participant, researcher, starts_at=at("2024-02-05", "22:30"), ends_at=at("2024-02-05", "23:30"))


def test_generated_columns_are_computed_and_read_only(conn: psycopg.Connection) -> None:
    lab = Lab(conn)
    w = lab.world()
    s = lab.session(w.study, w.participant, w.researcher, starts_at=at("2024-02-05", "09:00"), ends_at=at("2024-02-05", "10:30"))
    duration, lower, upper = row(conn, 
        "SELECT duration_min, lower(during), upper(during) FROM lab.session WHERE session_id = %s", (s,))
    assert duration == 90
    assert lower == at("2024-02-05", "09:00") and upper == at("2024-02-05", "10:30")
    with violates(conn, errors.GeneratedAlways):
        conn.execute("UPDATE lab.session SET duration_min = 5 WHERE session_id = %s", (s,))


def test_updated_at_moves_when_a_row_changes(conn: psycopg.Connection) -> None:
    lab = Lab(conn)
    w = lab.world()
    s = lab.session(w.study, w.participant, w.researcher)
    conn.execute("UPDATE lab.session SET updated_at = '2000-01-01' WHERE session_id = %s", (s,))  # the trigger overrides it
    (stamp,) = row(conn, "SELECT updated_at FROM lab.session WHERE session_id = %s", (s,))
    assert stamp.year >= 2024


def test_identity_ids_cannot_be_chosen_by_hand(conn: psycopg.Connection) -> None:
    with violates(conn, errors.GeneratedAlways):
        conn.execute("INSERT INTO lab.study (study_id, code, title, started_on, target_n) "
                     "VALUES (99, 'ABC-01', 'Some title', '2024-01-01', 5)")


def test_a_session_with_recordings_cannot_be_deleted(conn: psycopg.Connection) -> None:
    """Deleting a session would delete its booked devices, which the recordings depend on: refused."""
    lab = Lab(conn)
    w = lab.world()
    s = lab.booked_session(w)
    lab.recording(s, w.device)
    with violates(conn, errors.ForeignKeyViolation, "recording_session_device_fk"):
        conn.execute("DELETE FROM lab.session WHERE session_id = %s", (s,))


def test_a_session_without_recordings_takes_its_bookings_with_it(conn: psycopg.Connection) -> None:
    lab = Lab(conn)
    w = lab.world()
    s = lab.booked_session(w)
    conn.execute("DELETE FROM lab.session WHERE session_id = %s", (s,))
    assert scalar(conn, "SELECT count(*) FROM lab.session_device WHERE session_id = %s", (s,)) == 0


def test_a_study_with_participants_cannot_be_deleted(conn: psycopg.Connection) -> None:
    lab = Lab(conn)
    w = lab.world()
    with violates(conn, errors.ForeignKeyViolation):
        conn.execute("DELETE FROM lab.study WHERE study_id = %s", (w.study,))


def test_deleting_a_recording_deletes_its_channels_trials_and_features(conn: psycopg.Connection) -> None:
    lab = Lab(conn)
    w = lab.world()
    rec = lab.recording(lab.booked_session(w), w.device)
    conn.execute("INSERT INTO lab.channel (recording_id, channel_no, label, unit) VALUES (%s, 1, 'biceps', 'uV')", (rec,))
    trial = lab.trial(rec)
    conn.execute("INSERT INTO lab.trial_feature (trial_id, channel_no, feature_id, value) VALUES (%s, 1, 1, 12.5)", (trial,))
    conn.execute("DELETE FROM lab.recording WHERE recording_id = %s", (rec,))
    for table in ("channel", "trial"):
        assert scalar(conn, f"SELECT count(*) FROM lab.{table} WHERE recording_id = %s", (rec,)) == 0
    assert scalar(conn, "SELECT count(*) FROM lab.trial_feature WHERE trial_id = %s", (trial,)) == 0


def test_channel_rules(conn: psycopg.Connection) -> None:
    lab = Lab(conn)
    w = lab.world()
    rec = lab.recording(lab.booked_session(w), w.device)
    with violates(conn, errors.CheckViolation, "channel_no_positive"):
        conn.execute("INSERT INTO lab.channel VALUES (%s, 0, 'x', 'uV')", (rec,))
    with violates(conn, errors.CheckViolation, "channel_unit_values"):
        conn.execute("INSERT INTO lab.channel VALUES (%s, 1, 'x', 'kg')", (rec,))


def test_trial_numbers_are_unique_within_a_recording(conn: psycopg.Connection) -> None:
    lab = Lab(conn)
    w = lab.world()
    rec = lab.recording(lab.booked_session(w), w.device)
    lab.trial(rec, trial_no=1)
    lab.trial(rec, trial_no=2)
    with violates(conn, errors.UniqueViolation, "trial_number_unique"):
        lab.trial(rec, trial_no=2)


@pytest.mark.parametrize("value", ["'NaN'::float8", "'Infinity'::float8", "'-Infinity'::float8"])
def test_feature_values_must_be_finite(conn: psycopg.Connection, value: str) -> None:
    lab = Lab(conn)
    w = lab.world()
    trial = lab.trial(lab.recording(lab.booked_session(w), w.device))
    with violates(conn, errors.CheckViolation, "trial_feature_finite"):
        conn.execute(f"INSERT INTO lab.trial_feature VALUES (%s, 1, 1, {value})", (trial,))


def test_feature_rules(conn: psycopg.Connection) -> None:
    lab = Lab(conn)
    w = lab.world()
    trial = lab.trial(lab.recording(lab.booked_session(w), w.device))
    with violates(conn, errors.CheckViolation, "trial_feature_channel_positive"):
        conn.execute("INSERT INTO lab.trial_feature VALUES (%s, 0, 1, 1.0)", (trial,))
    with violates(conn, errors.ForeignKeyViolation, "trial_feature_feature_id_fkey"):
        conn.execute("INSERT INTO lab.trial_feature VALUES (%s, 1, 99, 1.0)", (trial,))
    conn.execute("INSERT INTO lab.trial_feature VALUES (%s, 1, 1, 1.0)", (trial,))
    with violates(conn, errors.UniqueViolation, "trial_feature_pkey"):
        conn.execute("INSERT INTO lab.trial_feature VALUES (%s, 1, 1, 2.0)", (trial,))


def test_the_feature_catalogue_has_one_row_per_modality_and_name(conn: psycopg.Connection) -> None:
    with violates(conn, errors.UniqueViolation, "feature_def_modality_name_key"):
        conn.execute("INSERT INTO lab.feature_def VALUES (99, 'emg', 'rms', 'uV', 'again')")


def test_the_database_does_not_check_that_a_feature_matches_the_modality(conn: psycopg.Connection) -> None:
    """A limit worth knowing: nothing stops an EEG band power from being stored on an EMG recording. That
    rule spans three tables, so the project checks it with a query instead (labtrack check)."""
    lab = Lab(conn)
    w = lab.world()
    trial = lab.trial(lab.recording(lab.booked_session(w), w.device, modality="emg"))
    conn.execute("INSERT INTO lab.trial_feature VALUES (%s, 1, 11, 5.0)", (trial,))  # feature 11 is alpha power (EEG)
    from labtrack.checks import run_checks
    results = {check.name: n for check, n in run_checks(conn)}
    assert results["feature_of_wrong_modality"] == 1
