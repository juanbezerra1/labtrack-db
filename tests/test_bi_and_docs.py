"""The reporting star schema, its CSV export, and the generated documentation."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from typing import Any

import pytest

from labtrack.db import connect, project_root, row, scalar
from labtrack.dictionary import generate
from labtrack.exports import EXPORT_VIEWS, export_csv

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
