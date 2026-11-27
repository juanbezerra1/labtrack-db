"""The reporting star schema, its CSV export, and the generated documentation."""

from __future__ import annotations

import csv
import hashlib
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest

from labtrack.db import connect, project_root, row, scalar
from labtrack.dictionary import generate
from labtrack.exports import EXPORT_VIEWS, export_csv
from labtrack.queries import load_queries, run_query

from .builders import Lab, at

ROOT = project_root()


# ---- the star schema is a real star: no fact points at a missing dimension row ------------------
ORPHAN_CHECKS = {
    "session -> study": "SELECT count(*) FROM bi.fact_session f LEFT JOIN bi.dim_study d ON d.study_key = f.study_key WHERE d.study_key IS NULL",
    "session -> participant": "SELECT count(*) FROM bi.fact_session f LEFT JOIN bi.dim_participant d USING (participant_key) WHERE d.participant_key IS NULL",
    "session -> researcher": "SELECT count(*) FROM bi.fact_session f LEFT JOIN bi.dim_researcher d USING (researcher_key) WHERE d.researcher_key IS NULL",
    "session -> date": "SELECT count(*) FROM bi.fact_session f LEFT JOIN bi.dim_date d USING (date_key) WHERE d.date_key IS NULL",
    "recording -> session": "SELECT count(*) FROM bi.fact_recording f LEFT JOIN bi.fact_session d USING (session_key) WHERE d.session_key IS NULL",
    "recording -> device": "SELECT count(*) FROM bi.fact_recording f LEFT JOIN bi.dim_device d USING (device_key) WHERE d.device_key IS NULL",
    "recording -> date": "SELECT count(*) FROM bi.fact_recording f LEFT JOIN bi.dim_date d USING (date_key) WHERE d.date_key IS NULL",
    "trial -> recording": "SELECT count(*) FROM bi.fact_trial f LEFT JOIN bi.fact_recording d USING (recording_key) WHERE d.recording_key IS NULL",
    "trial -> date": "SELECT count(*) FROM bi.fact_trial f LEFT JOIN bi.dim_date d USING (date_key) WHERE d.date_key IS NULL",
}


@pytest.mark.parametrize("name, sql", ORPHAN_CHECKS.items(), ids=list(ORPHAN_CHECKS))
def test_no_fact_row_points_at_a_missing_dimension_row(small_dsn: str, name: str, sql: str) -> None:
    with connect(small_dsn) as conn:
        assert scalar(conn, sql) == 0, name


@pytest.mark.parametrize("view, key", [("fact_session", "session_key"), ("fact_recording", "recording_key"), ("fact_trial", "trial_key"),
                                        ("dim_study", "study_key"), ("dim_participant", "participant_key"), ("dim_date", "date_key")])
def test_the_grain_one_row_per_key(small_dsn: str, view: str, key: str) -> None:
    with connect(small_dsn) as conn:
        rows, distinct = row(conn, f"SELECT count(*), count(DISTINCT {key}) FROM bi.{view}")
        assert rows == distinct > 0


def test_the_facts_add_up_to_the_source_tables(small_dsn: str) -> None:
    """A join in a view can silently multiply rows. These totals must match the tables they come from."""
    with connect(small_dsn) as conn:

        def q(query: str) -> Any:
            return scalar(conn, query)

        assert q("SELECT count(*) FROM bi.fact_session") == q("SELECT count(*) FROM lab.session")
        assert q("SELECT count(*) FROM bi.fact_recording") == q("SELECT count(*) FROM lab.recording")
        assert q("SELECT count(*) FROM bi.fact_trial") == q("SELECT count(*) FROM lab.trial")
        assert q("SELECT sum(n_recordings) FROM bi.fact_session") == q("SELECT count(*) FROM lab.recording")
        assert q("SELECT sum(n_trials) FROM bi.fact_recording") == q("SELECT count(*) FROM lab.trial")
        # hours_recorded is rounded to 3 decimals in each session, so the two totals may differ by up to half a
        # thousandth of an hour per session that has recordings, and by nothing more than that.
        assert q("""SELECT abs((SELECT sum(hours_recorded) FROM bi.fact_session)
                              - (SELECT sum(duration_s) / 3600.0 FROM lab.recording)::numeric)
                           <= 0.0005 * (SELECT count(*) FROM bi.fact_session WHERE n_recordings > 0)""")


# ---- the feature columns and the calibration flag (migration 0013) ------------------------------
FEATURE_COLUMNS = {
    "rms_mean_uv": "emg", "mnf_hz": "emg", "mdf_hz": "emg",
    "alpha_power_uv2": "eeg",
    "peak_force_n": "force", "force_cv_pct": "force",
}


@pytest.mark.parametrize("column, modality", FEATURE_COLUMNS.items(), ids=list(FEATURE_COLUMNS))
def test_a_feature_column_is_filled_for_its_own_modality_and_empty_for_the_others(
        small_dsn: str, column: str, modality: str) -> None:
    with connect(small_dsn) as conn:
        own, own_filled, elsewhere_filled = row(conn, f"""
            SELECT count(*) FILTER (WHERE modality = %s),
                   count({column}) FILTER (WHERE modality = %s),
                   count({column}) FILTER (WHERE modality <> %s)
            FROM bi.fact_trial""", (modality, modality, modality))
    assert own > 0
    assert own_filled == own, f"{column} should be filled for every {modality} trial"
    assert elsewhere_filled == 0, f"{column} should be empty for the other modalities"


FEATURE_NAMES = {            # column -> (feature in lab.feature_def, how a trial's channels are combined)
    "rms_mean_uv": ("rms", "avg"), "mnf_hz": ("mnf", "avg"), "mdf_hz": ("mdf", "avg"),
    "alpha_power_uv2": ("power_alpha", "avg"), "peak_force_n": ("peak_force", "max"), "force_cv_pct": ("force_cv", "avg"),
}


@pytest.mark.parametrize("column", list(FEATURE_NAMES))
def test_each_feature_column_holds_the_feature_it_is_named_after(small_dsn: str, column: str) -> None:
    """The view picks features by id; this test looks them up by name in the catalogue, so an id that points at the
    wrong feature (MNF where MDF was meant) cannot hide behind a column that is merely filled."""
    feature, how = FEATURE_NAMES[column]
    with connect(small_dsn) as conn:
        filled = scalar(conn, f"SELECT count({column}) FROM bi.fact_trial")
        wrong = scalar(conn, f"""
            SELECT count(*)
            FROM bi.fact_trial AS t
            JOIN (SELECT tf.trial_id, {how}(tf.value) AS v
                  FROM lab.trial_feature AS tf JOIN lab.feature_def AS f USING (feature_id)
                  WHERE f.name = %s GROUP BY tf.trial_id) AS x ON x.trial_id = t.trial_key
            WHERE t.{column} IS DISTINCT FROM round(x.v::numeric, 3)""", (feature,))
    assert filled > 0 and wrong == 0


def test_force_variability_in_the_star_is_the_number_query_10_computes(small_dsn: str) -> None:
    """Query 10 reads the long trial_feature table; the star carries the same feature as a column. The two roads must
    meet. The column is rounded to 3 decimals in each trial, hence the tolerance of one thousandth."""
    query = next(q for q in load_queries() if q.number == 10)
    with connect(small_dsn) as conn:
        _, expected = run_query(conn, query.variants[0][1])
        _, from_star = run_query(conn, """
            SELECT s.group_label,
                   count(t.force_cv_pct),
                   avg(t.force_cv_pct) FILTER (WHERE right(t.condition, 3) = '_fb'),
                   avg(t.force_cv_pct) FILTER (WHERE right(t.condition, 3) <> '_fb')
            FROM bi.fact_trial AS t
            JOIN bi.fact_session AS s USING (session_key)
            JOIN bi.dim_study AS st USING (study_key)
            WHERE st.study_code = 'FFB-01' AND t.valid AND t.force_cv_pct IS NOT NULL
            GROUP BY s.group_label ORDER BY s.group_label""")
    assert [r[0] for r in from_star] == [r[0] for r in expected] and len(expected) == 2
    for star_row, query_row in zip(from_star, expected, strict=True):
        assert star_row[1] == query_row[1]                                          # the same number of values
        assert abs(star_row[2] - query_row[2]) <= Decimal("0.001")                  # feedback on
        assert abs(star_row[3] - query_row[3]) <= Decimal("0.001")                  # feedback off


@pytest.mark.parametrize("dsn_fixture", ["small_dsn", "medium_dsn"])
def test_the_calibration_flag_flags_what_query_4_finds(dsn_fixture: str, request: pytest.FixtureRequest) -> None:
    query = next(q for q in load_queries() if q.number == 4)
    with connect(request.getfixturevalue(dsn_fixture)) as conn:
        _, found = run_query(conn, query.variants[0][1])
        flagged: dict[str, int] = dict(conn.execute("""
            SELECT d.serial_no, count(*)
            FROM bi.fact_recording AS f JOIN bi.dim_device AS d USING (device_key)
            WHERE NOT f.device_calibrated GROUP BY d.serial_no""").fetchall())
    assert flagged == {r[0]: r[2] for r in found}
    assert sum(flagged.values()) > 0


def test_the_calibration_flag_follows_the_rule_day_by_day(conn: psycopg.Connection) -> None:
    """A calibration covers the days from performed_on up to, not including, valid_until; only a passed one counts;
    and the day is the lab's calendar day, not the UTC one."""
    lab = Lab(conn)
    world = lab.world()
    lab.calibration(world.device, world.researcher, performed_on="2024-02-05", valid_until="2024-02-10", passed=True)
    lab.calibration(world.device, world.researcher, performed_on="2024-03-01", valid_until="2024-03-20", passed=False)
    session = lab.booked_session(world, status="completed")
    cases = [
        (("2024-02-04", "23:59"), False),    # the day before the calibration
        (("2024-02-05", "00:00"), True),     # performed_on itself is covered
        (("2024-02-09", "22:30"), True),     # already the 10th in UTC, still the 9th in the lab
        (("2024-02-10", "00:00"), False),    # valid_until is the first day NOT covered
        (("2024-03-05", "09:00"), False),    # that calibration failed
    ]
    for block_no, ((day, hm), _) in enumerate(cases, start=1):
        lab.recording(session, world.device, block_no=block_no, recorded_at=at(day, hm))
    flags = [r[0] for r in conn.execute("SELECT device_calibrated FROM bi.fact_recording ORDER BY recording_key").fetchall()]
    assert flags == [expected for _, expected in cases]


# ---- the CSV export -----------------------------------------------------------------------------
def test_the_export_is_complete_and_readable(small_dsn: str, tmp_path: Path) -> None:
    with connect(small_dsn) as conn:
        counts = export_csv(conn, tmp_path)
    assert list(counts) == EXPORT_VIEWS
    for view, n in counts.items():
        with (tmp_path / f"{view}.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        assert len(rows) == n + 1 and len(set(map(len, rows))) == 1, view
    with connect(small_dsn) as conn:
        assert counts["fact_session"] == scalar(conn, "SELECT count(*) FROM lab.session")


def test_the_export_spells_booleans_and_nulls_plainly(small_dsn: str, tmp_path: Path) -> None:
    with connect(small_dsn) as conn:
        export_csv(conn, tmp_path)
    with (tmp_path / "fact_trial.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert {r["valid"] for r in rows} == {"true", "false"}
    assert any(r["reject_reason"] == "" for r in rows) and any(r["rms_mean_uv"] == "" for r in rows)   # NULL is an empty cell
    assert b"\r" not in (tmp_path / "fact_trial.csv").read_bytes()


def test_the_committed_export_is_what_the_small_seed_produces(small_dsn: str, tmp_path: Path) -> None:
    """exports/small/ is committed so the Power BI project can start without a database. If this fails after you
    changed the seed or the bi views on purpose:  labtrack seed --scale small --reset  &&  labtrack export --out exports/small"""
    with connect(small_dsn) as conn:
        export_csv(conn, tmp_path)
    committed = ROOT / "exports" / "small"
    assert (committed / "SHA256SUMS").exists(), "exports/small/ is missing"
    assert (tmp_path / "SHA256SUMS").read_text(encoding="utf-8") == (committed / "SHA256SUMS").read_text(encoding="utf-8").replace("\r\n", "\n")
    for view in EXPORT_VIEWS:
        assert hashlib.sha256((tmp_path / f"{view}.csv").read_bytes()).hexdigest() == \
               hashlib.sha256((committed / f"{view}.csv").read_bytes().replace(b"\r\n", b"\n")).hexdigest(), view


# ---- the documentation generated from the catalog -----------------------------------------------
def test_the_data_dictionary_is_up_to_date(migrated_dsn: str) -> None:
    """If this fails after you changed the schema:  labtrack dictionary --out docs/data-dictionary.md"""
    with connect(migrated_dsn) as conn:
        generated = generate(conn)
    committed = (ROOT / "docs" / "data-dictionary.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert generated == committed
