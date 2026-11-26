"""Each data-quality check must be able to find its own kind of damage. A check that cannot fail is decoration."""

from __future__ import annotations

from collections.abc import Callable

import psycopg
import pytest

from labtrack.checks import CHECKS, run_checks

from .builders import Scene, at, healthy_scene


def findings(conn: psycopg.Connection) -> dict[str, int]:
    return {check.name: n for check, n in run_checks(conn)}


def double_booked(conn: psycopg.Connection, s: Scene) -> None:
    conn.execute("ALTER TABLE lab.session DROP CONSTRAINT session_room_no_overlap")   # DDL is transactional: undone at the end
    s.lab.booked_session(s.world, visit_no=2, status="completed")                      # the same room at the same hours


def out_of_order(conn: psycopg.Connection, s: Scene) -> None:
    s.lab.booked_session(s.world, visit_no=2, starts_at=at("2024-02-01"), ends_at=at("2024-02-01", "10:30"))


def no_recording(conn: psycopg.Connection, s: Scene) -> None:
    s.lab.booked_session(s.world, visit_no=2, starts_at=at("2024-02-12"), ends_at=at("2024-02-12", "10:30"),
                         status="completed")


def recorded_on_another_day(conn: psycopg.Connection, s: Scene) -> None:
    conn.execute("UPDATE lab.recording SET recorded_at = %s WHERE recording_id = %s", (at("2024-03-01"), s.recording))


def session_cancelled_later(conn: psycopg.Connection, s: Scene) -> None:
    conn.execute("UPDATE lab.session SET status = 'cancelled' WHERE session_id = %s", (s.session,))


def trial_runs_past_the_end(conn: psycopg.Connection, s: Scene) -> None:
    conn.execute("UPDATE lab.trial SET onset_s = 59 WHERE trial_id = %s", (s.trial,))     # 59 + 6 s in a 60 s recording


def value_for_channel_nine(conn: psycopg.Connection, s: Scene) -> None:
    conn.execute("INSERT INTO lab.trial_feature VALUES (%s, 9, 1, 10.0)", (s.trial,))     # the recording has 4 channels


def alpha_power_on_an_emg_recording(conn: psycopg.Connection, s: Scene) -> None:
    conn.execute("INSERT INTO lab.trial_feature VALUES (%s, 1, 11, 5.0)", (s.trial,))     # feature 11 is an EEG one


def a_channel_goes_missing(conn: psycopg.Connection, s: Scene) -> None:
    conn.execute("DELETE FROM lab.channel WHERE recording_id = %s AND channel_no = 4", (s.recording,))


def withdrawal_moved_back(conn: psycopg.Connection, s: Scene) -> None:
    conn.execute("UPDATE lab.participant SET withdrawn_on = '2024-01-20' WHERE participant_id = %s", (s.world.participant,))


def retirement_moved_back(conn: psycopg.Connection, s: Scene) -> None:
    conn.execute("UPDATE lab.device SET retired_on = '2024-02-01' WHERE device_id = %s", (s.world.device,))


def researcher_left_earlier(conn: psycopg.Connection, s: Scene) -> None:
    conn.execute("UPDATE lab.researcher SET left_on = '2024-02-01' WHERE researcher_id = %s", (s.world.researcher,))


DAMAGE: dict[str, Callable[[psycopg.Connection, Scene], None]] = {
    "room_double_booked": double_booked,
    "visits_out_of_order": out_of_order,
    "completed_without_recording": no_recording,
    "recording_outside_session": recorded_on_another_day,
    "recording_of_uncompleted_session": session_cancelled_later,
    "trial_beyond_recording": trial_runs_past_the_end,
    "feature_for_missing_channel": value_for_channel_nine,
    "feature_of_wrong_modality": alpha_power_on_an_emg_recording,
    "channel_count_mismatch": a_channel_goes_missing,
    "session_after_withdrawal": withdrawal_moved_back,
    "device_used_after_retirement": retirement_moved_back,
    "researcher_not_employed": researcher_left_earlier,
}


def test_every_check_has_a_damage_scenario() -> None:
    assert set(DAMAGE) == {check.name for check in CHECKS}


def test_a_healthy_lab_passes_every_check(conn: psycopg.Connection) -> None:
    healthy_scene(conn)
    assert findings(conn) == {check.name: 0 for check in CHECKS}


@pytest.mark.parametrize("name", [check.name for check in CHECKS])
def test_each_check_finds_its_own_kind_of_damage(conn: psycopg.Connection, name: str) -> None:
    scene = healthy_scene(conn)
    DAMAGE[name](conn, scene)
    assert findings(conn)[name] >= 1, f"the check {name} did not notice the damage made for it"
