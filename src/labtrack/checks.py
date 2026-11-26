"""Data-quality checks: questions that must always be answered "none".

Constraints stop bad rows at the door, but some rules cannot be a constraint (they compare many rows,
or they depend on something that changes later). Each check below is a SELECT that returns the number
of rows that break one rule. `labtrack check` runs them all; the test-suite runs them after seeding.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg

from .db import scalar


@dataclass(frozen=True)
class Check:
    name: str
    rule: str
    sql: str  # returns one number: how many rows break the rule


CHECKS: list[Check] = [
    Check(
        "room_double_booked",
        "no two scheduled or completed sessions overlap in the same room "
        "(the exclusion constraint's promise, re-checked)",
        """SELECT count(*) FROM lab.session a JOIN lab.session b
             ON a.room = b.room AND a.session_id < b.session_id AND a.during && b.during
           WHERE a.status IN ('scheduled', 'completed') AND b.status IN ('scheduled', 'completed')""",
    ),
    Check(
        "visits_out_of_order",
        "a participant's visit n+1 starts after visit n (within one study)",
        """SELECT count(*) FROM (
               SELECT starts_at,
                      lag(starts_at) OVER (PARTITION BY study_id, participant_id ORDER BY visit_no) AS previous
               FROM lab.session WHERE status IN ('scheduled', 'completed')) AS t
           WHERE previous IS NOT NULL AND starts_at <= previous""",
    ),
    Check(
        "completed_without_recording",
        "every completed session has at least one recording",
        """SELECT count(*) FROM lab.session s
           WHERE s.status = 'completed'
             AND NOT EXISTS (SELECT 1 FROM lab.recording r WHERE r.session_id = s.session_id)""",
    ),
    Check(
        "recording_outside_session",
        "a recording starts while its session is running",
        """SELECT count(*) FROM lab.recording r JOIN lab.session s USING (session_id)
           WHERE r.recorded_at < s.starts_at OR r.recorded_at >= s.ends_at""",
    ),
    Check(
        "recording_of_uncompleted_session",
        "recordings only exist for completed sessions",
        """SELECT count(*) FROM lab.recording r JOIN lab.session s USING (session_id) WHERE s.status <> 'completed'""",
    ),
    Check(
        "trial_beyond_recording",
        "a trial ends before its recording does",
        """SELECT count(*) FROM lab.trial t JOIN lab.recording r USING (recording_id)
           WHERE t.onset_s + t.duration_s > r.duration_s""",
    ),
    Check(
        "feature_for_missing_channel",
        "a feature value refers to a channel the recording actually has",
        """SELECT count(*) FROM lab.trial_feature tf
             JOIN lab.trial t USING (trial_id) JOIN lab.recording r USING (recording_id)
           WHERE tf.channel_no > r.n_channels""",
    ),
    Check(
        "feature_of_wrong_modality",
        "a feature belongs to the modality of its recording (no EEG power on an EMG recording)",
        """SELECT count(*) FROM lab.trial_feature tf
             JOIN lab.feature_def f USING (feature_id)
             JOIN lab.trial t USING (trial_id) JOIN lab.recording r USING (recording_id)
           WHERE f.modality <> r.modality""",
    ),
    Check(
        "channel_count_mismatch",
        "a recording has exactly n_channels channel rows",
        """SELECT count(*) FROM lab.recording r
           WHERE r.n_channels <> (SELECT count(*) FROM lab.channel c WHERE c.recording_id = r.recording_id)""",
    ),
    Check(
        "session_after_withdrawal",
        "no active session after the participant withdrew (the trigger checks this on write; this catches later edits)",
        """SELECT count(*) FROM lab.session s JOIN lab.participant p USING (participant_id)
           WHERE s.status IN ('scheduled', 'completed') AND p.withdrawn_on IS NOT NULL
             AND (s.starts_at AT TIME ZONE 'America/Sao_Paulo')::date > p.withdrawn_on""",
    ),
    Check(
        "device_used_after_retirement",
        "no session books a device after its retirement date",
        """SELECT count(*) FROM lab.session_device sd JOIN lab.session s USING (session_id)
             JOIN lab.device d USING (device_id)
           WHERE d.retired_on IS NOT NULL AND (s.starts_at AT TIME ZONE 'America/Sao_Paulo')::date >= d.retired_on""",
    ),
    Check(
        "researcher_not_employed",
        "the researcher of a session was employed on that day",
        """SELECT count(*) FROM lab.session s JOIN lab.researcher r USING (researcher_id)
           WHERE (s.starts_at AT TIME ZONE 'America/Sao_Paulo')::date < r.hired_on
              OR (r.left_on IS NOT NULL AND (s.starts_at AT TIME ZONE 'America/Sao_Paulo')::date >= r.left_on)""",
    ),
]


def run_checks(conn: psycopg.Connection) -> list[tuple[Check, int]]:
    return [(check, int(scalar(conn, check.sql))) for check in CHECKS]
