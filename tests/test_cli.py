"""The command line: every command runs and says something useful, and the errors are readable."""

from __future__ import annotations

import subprocess
import sys
import uuid
from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest

from labtrack import __version__
from labtrack.checks import CHECKS
from labtrack.cli import main
from labtrack.db import connect, with_dbname
from labtrack.explain import load_lessons
from labtrack.exports import EXPORT_VIEWS
from labtrack.migrate import load_migrations, migrate
from labtrack.queries import load_queries

from .builders import healthy_scene


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    code = main(list(args))
    out, err = capsys.readouterr()
    return code, out, err


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main(["--version"])
    assert info.value.code == 0
    assert f"labtrack {__version__}" in capsys.readouterr().out


def test_python_dash_m_labtrack_is_the_same_program() -> None:
    done = subprocess.run([sys.executable, "-m", "labtrack", "--version"], capture_output=True, text=True, check=True)
    assert done.stdout.strip() == f"labtrack {__version__}"


# ---- migrations -------------------------------------------------------------------------------
def test_status_lists_every_migration_as_applied(capsys: pytest.CaptureFixture[str], migrated_dsn: str) -> None:
    code, out, _ = run(capsys, "--dsn", migrated_dsn, "status")
    lines = out.strip().splitlines()
    assert code == 0 and len(lines) == len(load_migrations())
    assert all("applied" in line for line in lines)


def test_migrate_says_when_there_is_nothing_to_do(capsys: pytest.CaptureFixture[str], migrated_dsn: str) -> None:
    code, out, _ = run(capsys, "--dsn", migrated_dsn, "migrate")
    assert code == 0 and "nothing to apply" in out


def test_migrate_to_a_version_leaves_the_rest_pending(
    capsys: pytest.CaptureFixture[str], make_db: Callable[[], str]
) -> None:
    dsn = make_db()
    code, out, _ = run(capsys, "--dsn", dsn, "migrate", "--to", "2")
    assert code == 0 and "2 migration(s) applied" in out
    code, out, _ = run(capsys, "--dsn", dsn, "status")
    states = [line.split()[1] for line in out.strip().splitlines()]
    assert code == 0 and states == ["applied"] * 2 + ["pending"] * (len(load_migrations()) - 2)


def test_status_exits_with_1_when_an_applied_file_was_changed(
    capsys: pytest.CaptureFixture[str], make_db: Callable[[], str]
) -> None:
    dsn = make_db()
    with connect(dsn) as conn:
        migrate(conn, log=lambda _: None)
        conn.execute("UPDATE public.schema_migrations SET checksum = 'edited' WHERE version = 1")
    code, out, _ = run(capsys, "--dsn", dsn, "status")
    assert code == 1 and "changed" in out


# ---- data -------------------------------------------------------------------------------------
def test_counts_prints_every_data_table(capsys: pytest.CaptureFixture[str], small_dsn: str) -> None:
    code, out, _ = run(capsys, "--dsn", small_dsn, "counts")
    assert code == 0
    assert "participant" in out and "trial_feature" in out and "314,368" in out


def test_seeding_twice_is_refused_with_a_hint(capsys: pytest.CaptureFixture[str], small_dsn: str) -> None:
    code, _, err = run(capsys, "--dsn", small_dsn, "seed", "--scale", "tiny")
    assert code == 1 and "already has data" in err and "--reset" in err


def test_an_unknown_scale_is_refused_by_the_parser(small_dsn: str) -> None:
    with pytest.raises(SystemExit) as info:
        main(["--dsn", small_dsn, "seed", "--scale", "huge"])
    assert info.value.code == 2


def test_check_passes_on_clean_data(capsys: pytest.CaptureFixture[str], small_dsn: str) -> None:
    code, out, _ = run(capsys, "--dsn", small_dsn, "check")
    assert code == 0 and f"{len(CHECKS)} of {len(CHECKS)} checks passed" in out


def test_check_exits_with_1_and_names_the_failing_check(
    capsys: pytest.CaptureFixture[str], make_db: Callable[[], str]
) -> None:
    dsn = make_db()
    with connect(dsn) as conn:
        migrate(conn, log=lambda _: None)
        scene = healthy_scene(conn)
        conn.execute("INSERT INTO lab.trial_feature VALUES (%s, 1, 11, 5.0)", (scene.trial,))  # an EEG feature on EMG
    code, out, _ = run(capsys, "--dsn", dsn, "check")
    assert code == 1
    assert "FAIL feature_of_wrong_modality" in out and f"{len(CHECKS) - 1} of {len(CHECKS)} checks passed" in out


# ---- queries and lessons ----------------------------------------------------------------------
def test_query_without_a_number_lists_them_all(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "query")  # listing needs no database
    assert code == 0
    for query in load_queries():
        assert query.title in out


def test_query_runs_one_and_can_show_its_sql(capsys: pytest.CaptureFixture[str], small_dsn: str) -> None:
    code, out, _ = run(capsys, "--dsn", small_dsn, "query", "1", "--show")
    assert code == 0
    assert out.startswith("-- Query 1:") and "SELECT" in out and "(10 rows)" in out


def test_query_errors_are_readable(capsys: pytest.CaptureFixture[str], small_dsn: str) -> None:
    code, _, err = run(capsys, "--dsn", small_dsn, "query", "99")
    assert code == 1 and "no query number 99" in err
    code, _, err = run(capsys, "--dsn", small_dsn, "query", "3", "--variant", "nope")
    assert code == 1 and "no variant 'nope'" in err


def test_explain_lab_without_a_number_lists_the_lessons(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "explain-lab")
    assert code == 0
    for lesson in load_lessons():
        assert lesson.title in out


def test_explain_lab_warns_when_the_database_is_too_small(capsys: pytest.CaptureFixture[str], tiny_dsn: str) -> None:
    _, out, _ = run(capsys, "--dsn", tiny_dsn, "explain-lab", "2")
    assert "warning: this lesson needs the medium scale" in out
    assert "labtrack seed --scale medium --reset" in out


def test_explain_lab_unknown_lesson(capsys: pytest.CaptureFixture[str], tiny_dsn: str) -> None:
    code, _, err = run(capsys, "--dsn", tiny_dsn, "explain-lab", "99")
    assert code == 1 and "no lesson 99" in err


# ---- exports and documentation ----------------------------------------------------------------
def test_export_writes_every_view_and_the_checksums(
    capsys: pytest.CaptureFixture[str], small_dsn: str, tmp_path: Path
) -> None:
    code, out, _ = run(capsys, "--dsn", small_dsn, "export", "--out", str(tmp_path))
    assert code == 0 and "SHA256SUMS" in out
    assert {p.name for p in tmp_path.iterdir()} == {f"{view}.csv" for view in EXPORT_VIEWS} | {"SHA256SUMS"}


def test_dictionary_prints_or_writes_the_same_text(
    capsys: pytest.CaptureFixture[str], migrated_dsn: str, tmp_path: Path
) -> None:
    code, printed, _ = run(capsys, "--dsn", migrated_dsn, "dictionary")
    assert code == 0 and printed.startswith("# Data dictionary")
    target = tmp_path / "dictionary.md"
    code, _, _ = run(capsys, "--dsn", migrated_dsn, "dictionary", "--out", str(target))
    assert code == 0 and target.read_text(encoding="utf-8") == printed


# ---- the database itself ----------------------------------------------------------------------
def test_createdb_creates_the_database_once(capsys: pytest.CaptureFixture[str], make_db: Callable[[], str]) -> None:
    server = make_db()
    name = f"labtrack_t_cli_{uuid.uuid4().hex[:8]}"
    dsn = with_dbname(server, name)
    try:
        code, out, _ = run(capsys, "--dsn", dsn, "createdb")
        assert code == 0 and f"created database '{name}'" in out
        code, out, _ = run(capsys, "--dsn", dsn, "createdb")
        assert code == 0 and "already exists" in out
    finally:
        with psycopg.connect(with_dbname(server, "postgres"), autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_an_unreachable_server_is_a_readable_error_that_does_not_print_the_password(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, err = run(capsys, "--dsn", "postgresql://someone:s3cret-word@127.0.0.1:1/nothing", "status")
    assert code == 1 and out == ""
    assert "could not connect" in err and "README" in err
    assert "s3cret-word" not in err
