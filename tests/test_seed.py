"""The synthetic data: reproducible, consistent, and carrying the patterns the lessons rely on."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest

from labtrack.checks import run_checks
from labtrack.db import connect, row, scalar
from labtrack.migrate import migrate
from labtrack.seed import DATA_TABLES, SeedError, counts, seed

from .golden import check_golden

PRIMARY_KEYS = {
    "study": "study_id",
    "researcher": "researcher_id",
    "participant": "participant_id",
    "enrollment": "study_id, participant_id",
    "device": "device_id",
    "calibration": "calibration_id",
    "session": "session_id",
    "session_device": "session_id, device_id",
    "recording": "recording_id",
    "channel": "recording_id, channel_no",
    "trial": "trial_id",
    "trial_feature": "trial_id, channel_no, feature_id",
}
quiet = lambda _msg: None  # noqa: E731


def digests(conn: psycopg.Connection) -> dict[str, str]:
    """An md5 of every row of every data table (minus the created_at/updated_at stamps, which are the real clock)."""
    return {
        table: scalar(
            conn,
            f"SELECT md5(coalesce(string_agg(((to_jsonb(t) - 'created_at') - 'updated_at')::text, E'\\n' ORDER BY {pk}), '')) "
            f"FROM lab.{table} AS t",
        )
        for table, pk in PRIMARY_KEYS.items()
    }


def test_every_data_table_is_covered() -> None:
    assert set(PRIMARY_KEYS) == set(DATA_TABLES)


def test_the_same_seed_gives_the_same_rows_every_time(make_db: Callable[[], str]) -> None:
    results = []
    for _ in range(2):
        with connect(make_db()) as conn:
            migrate(conn, log=quiet)
            seed(conn, scale="tiny", log=quiet)
            results.append(digests(conn))
    assert results[0] == results[1]


def test_another_as_of_date_gives_another_calendar(make_db: Callable[[], str]) -> None:
    with connect(make_db()) as conn:
        migrate(conn, log=quiet)
        seed(conn, scale="tiny", log=quiet)
        a = digests(conn)
        seed(conn, scale="tiny", as_of="2026-06-30", do_reset=True, log=quiet)
        b = digests(conn)
        assert a["participant"] != b["participant"] or a["session"] != b["session"]
        assert scalar(conn, "SELECT max(starts_at) <= %s::date + 43 FROM lab.session", ("2026-06-30",))


def test_row_counts_at_tiny_scale(request: pytest.FixtureRequest, tiny_dsn: str) -> None:
    with connect(tiny_dsn) as conn:
        check_golden(request, "seed_counts_tiny", counts(conn))


def test_row_counts_at_small_scale(request: pytest.FixtureRequest, small_dsn: str) -> None:
    with connect(small_dsn) as conn:
        check_golden(request, "seed_counts_small", counts(conn))


def test_row_counts_at_medium_scale(request: pytest.FixtureRequest, medium_dsn: str) -> None:
    with connect(medium_dsn) as conn:
        check_golden(request, "seed_counts_medium", counts(conn))


@pytest.mark.parametrize("dsn_fixture", ["tiny_dsn", "small_dsn"])
def test_the_data_quality_checks_find_nothing(request: pytest.FixtureRequest, dsn_fixture: str) -> None:
    with connect(request.getfixturevalue(dsn_fixture)) as conn:
        failing = {check.name: n for check, n in run_checks(conn) if n}
    assert failing == {}


def test_seeding_twice_needs_reset(make_db: Callable[[], str]) -> None:
    with connect(make_db()) as conn:
        migrate(conn, log=quiet)
        seed(conn, scale="tiny", log=quiet)
        first = digests(conn)
        with pytest.raises(SeedError, match="already has data"):
            seed(conn, scale="tiny", log=quiet)
        seed(conn, scale="tiny", do_reset=True, log=quiet)
        assert digests(conn) == first  # identity counters restart too, so even the ids are the same


def test_seed_needs_the_latest_migration(make_db: Callable[[], str]) -> None:
    with connect(make_db()) as conn:
        migrate(conn, target=5, log=quiet)
        with pytest.raises(SeedError, match="latest migration"):
            seed(conn, scale="tiny", log=quiet)


def test_unknown_scale_is_refused(migrated_dsn: str) -> None:
    with connect(migrated_dsn) as conn, pytest.raises(SeedError, match="unknown scale"):
        seed(conn, scale="huge", log=quiet)


def test_a_failing_seed_file_cleans_up_after_itself(make_db: Callable[[], str], tmp_path: Path) -> None:
    (tmp_path / "01_bad.sql").write_text("CREATE SCHEMA lab_seed; SELECT 1 / 0;", encoding="utf-8")
    with connect(make_db()) as conn:
        migrate(conn, log=quiet)
        with pytest.raises(SeedError, match="01_bad.sql failed"):
            seed(conn, scale="tiny", directory=tmp_path, log=quiet)
        assert scalar(conn, "SELECT to_regnamespace('lab_seed')") is None


def test_the_helper_schema_is_gone_and_the_materialized_view_is_filled(small_dsn: str) -> None:
    with connect(small_dsn) as conn:
        assert scalar(conn, "SELECT to_regnamespace('lab_seed')") is None
        assert scalar(conn, "SELECT count(*) FROM lab.mv_monthly_throughput") > 0


def test_nothing_is_dated_after_the_seed_day_except_bookings(small_dsn: str) -> None:
    with connect(small_dsn) as conn:
        conn.execute("SET TIME ZONE 'America/Sao_Paulo'")
        later_not_scheduled, scheduled_early, scheduled_too_far = row(
            conn,
            """SELECT count(*) FILTER (WHERE starts_at::date > DATE '2026-10-31' AND status <> 'scheduled' AND status <> 'cancelled'),
                      count(*) FILTER (WHERE starts_at::date <= DATE '2026-10-31' AND status = 'scheduled'),
                      count(*) FILTER (WHERE starts_at::date > DATE '2026-10-31' + 42)
               FROM lab.session""",
        )
        assert (later_not_scheduled, scheduled_early, scheduled_too_far) == (0, 0, 0)
        assert scalar(conn, "SELECT count(*) FROM lab.recording WHERE recorded_at::date > DATE '2026-10-31'") == 0


def test_every_kind_of_session_outcome_appears(small_dsn: str) -> None:
    with connect(small_dsn) as conn:
        states = {r[0] for r in conn.execute("SELECT DISTINCT status::text FROM lab.session")}
        assert states == {"scheduled", "completed", "cancelled", "no_show"}


def test_the_device_roster_is_the_answer_key_of_the_calibration_lesson(small_dsn: str) -> None:
    with connect(small_dsn) as conn:
        conn.execute("SET labtrack.as_of = '2026-10-31'")
        got: dict[str, int] = dict(
            conn.execute("SELECT calibration_status, count(*) FROM lab.v_device_status GROUP BY 1").fetchall()
        )
        assert got == {"ok": 18, "due_soon": 1, "overdue": 3, "never_calibrated": 1, "retired": 1}


def test_some_recordings_were_made_with_an_uncalibrated_device(small_dsn: str) -> None:
    with connect(small_dsn) as conn:
        n = scalar(
            conn,
            """SELECT count(*) FROM lab.recording r
               WHERE NOT EXISTS (SELECT 1 FROM lab.calibration c
                                 WHERE c.device_id = r.device_id AND c.passed
                                   AND c.performed_on <= r.recorded_at::date AND r.recorded_at::date < c.valid_until)""",
        )
        assert n > 0


def test_planted_effect_feedback_lowers_force_variability(small_dsn: str) -> None:
    with connect(small_dsn) as conn:
        rows = conn.execute(
            """SELECT right(t.condition, 3) = '_fb' AS feedback, e.group_label, avg(tf.value)
               FROM lab.trial_feature tf JOIN lab.trial t USING (trial_id) JOIN lab.recording r USING (recording_id)
                    JOIN lab.session s USING (session_id) JOIN lab.enrollment e USING (study_id, participant_id)
               WHERE tf.feature_id = 17
               GROUP BY 1, 2"""
        ).fetchall()
        cv = {(fb, grp): v for fb, grp, v in rows}
        assert cv[(True, "intervention")] < cv[(True, "control")] < cv[(False, "control")]
        assert cv[(True, "intervention")] < cv[(False, "intervention")]


def test_planted_effect_fatigue_lowers_frequency_and_raises_amplitude(small_dsn: str) -> None:
    with connect(small_dsn) as conn:
        by_feature = {}
        for name, pre, post in conn.execute(
            """SELECT f.name, avg(tf.value) FILTER (WHERE t.condition = 'fatigue_pre'),
                             avg(tf.value) FILTER (WHERE t.condition = 'fatigue_post')
               FROM lab.trial_feature tf JOIN lab.feature_def f USING (feature_id)
                    JOIN lab.trial t USING (trial_id)
               WHERE t.condition IN ('fatigue_pre', 'fatigue_post') AND f.name IN ('mnf', 'mdf', 'rms')
               GROUP BY f.name"""
        ):
            by_feature[name] = post / pre
        assert by_feature["mnf"] < 0.92 and by_feature["mdf"] < 0.92 and by_feature["rms"] > 1.05


def test_planted_effect_alpha_power_is_lower_with_the_large_stimulus(small_dsn: str) -> None:
    with connect(small_dsn) as conn:
        small, large = row(
            conn,
            """SELECT avg(tf.value) FILTER (WHERE t.condition = 'stimulus_small'),
                      avg(tf.value) FILTER (WHERE t.condition = 'stimulus_large')
               FROM lab.trial_feature tf JOIN lab.trial t USING (trial_id) WHERE tf.feature_id = 11""",
        )
        assert large < small
