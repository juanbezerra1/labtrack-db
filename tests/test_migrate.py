"""The migration runner, and the migrations themselves (including the zero-downtime sequence)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from psycopg import errors

from labtrack.db import connect, project_root, row, scalar
from labtrack.migrate import LOCK_KEY, MigrationError, load_migrations, migrate, status

quiet = lambda _msg: None  # noqa: E731


def write(folder: Path, name: str, sql: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(sql, encoding="utf-8", newline="\n")


# ----------------------------------------------------------------------------------------------
# The runner
# ----------------------------------------------------------------------------------------------
def test_applies_every_migration_in_order(make_db: Callable[[], str]) -> None:
    with connect(make_db()) as conn:
        done = migrate(conn, log=quiet)
        assert done == [m.label for m in load_migrations()]
        rows = conn.execute("SELECT version, checksum FROM public.schema_migrations ORDER BY version").fetchall()
        assert [r[0] for r in rows] == list(range(1, len(done) + 1))
        assert all(len(r[1]) == 64 for r in rows)


def test_a_second_run_does_nothing(make_db: Callable[[], str]) -> None:
    with connect(make_db()) as conn:
        migrate(conn, log=quiet)
        assert migrate(conn, log=quiet) == []
        assert {r["state"] for r in status(conn)} == {"applied"}


def test_target_stops_early_and_the_rest_can_follow(make_db: Callable[[], str]) -> None:
    with connect(make_db()) as conn:
        first = migrate(conn, target=7, log=quiet)
        assert len(first) == 7
        assert [r["state"] for r in status(conn)].count("pending") == len(load_migrations()) - 7
        rest = migrate(conn, log=quiet)
        assert len(first) + len(rest) == len(load_migrations())


def test_an_edited_migration_is_refused(make_db: Callable[[], str], tmp_path: Path) -> None:
    write(tmp_path, "0001_one.sql", "CREATE TABLE one (i integer);")
    with connect(make_db()) as conn:
        migrate(conn, directory=tmp_path, log=quiet)
        write(tmp_path, "0001_one.sql", "CREATE TABLE one (i integer, j integer);")
        with pytest.raises(MigrationError, match="changed after it was applied"):
            migrate(conn, directory=tmp_path, log=quiet)
        assert status(conn, tmp_path)[0]["state"] == "changed"


def test_a_missing_file_is_refused(make_db: Callable[[], str], tmp_path: Path) -> None:
    write(tmp_path, "0001_one.sql", "CREATE TABLE one (i integer);")
    write(tmp_path, "0002_two.sql", "CREATE TABLE two (i integer);")
    with connect(make_db()) as conn:
        migrate(conn, directory=tmp_path, log=quiet)
        (tmp_path / "0002_two.sql").unlink()
        with pytest.raises(MigrationError, match="its file is gone"):
            migrate(conn, directory=tmp_path, log=quiet)


def test_a_file_added_out_of_order_is_refused(make_db: Callable[[], str], tmp_path: Path) -> None:
    write(tmp_path, "0001_one.sql", "CREATE TABLE one (i integer);")
    write(tmp_path, "0003_three.sql", "CREATE TABLE three (i integer);")
    with connect(make_db()) as conn:
        migrate(conn, directory=tmp_path, log=quiet)
        write(tmp_path, "0002_two.sql", "CREATE TABLE two (i integer);")
        with pytest.raises(MigrationError, match="out of order"):
            migrate(conn, directory=tmp_path, log=quiet)


def test_a_failing_migration_leaves_nothing_behind(make_db: Callable[[], str], tmp_path: Path) -> None:
    """Transactional DDL: the CREATE TABLE before the error is undone together with the failed statement."""
    write(tmp_path, "0001_ok.sql", "CREATE TABLE ok (i integer);")
    write(tmp_path, "0002_bad.sql", "CREATE TABLE half_done (i integer);\nSELECT 1 / 0;")
    with connect(make_db()) as conn:
        with pytest.raises(errors.DivisionByZero):
            migrate(conn, directory=tmp_path, log=quiet)
        assert scalar(conn, "SELECT to_regclass('half_done')") is None
        assert scalar(conn, "SELECT to_regclass('ok')") == "ok"
        assert [r[0] for r in conn.execute("SELECT version FROM public.schema_migrations")] == [1]
        # and the lock was released, so a fixed migration can run right away
        write(tmp_path, "0002_bad.sql", "CREATE TABLE fixed (i integer);")
        assert migrate(conn, directory=tmp_path, log=quiet) == ["0002_bad"]


def test_two_runners_cannot_work_at_once(make_db: Callable[[], str], tmp_path: Path) -> None:
    write(tmp_path, "0001_one.sql", "CREATE TABLE one (i integer);")
    dsn = make_db()
    with connect(dsn) as holder, connect(dsn) as conn:
        holder.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
        with pytest.raises(MigrationError, match="another migration run is in progress"):
            migrate(conn, directory=tmp_path, log=quiet)
        holder.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
        assert migrate(conn, directory=tmp_path, log=quiet) == ["0001_one"]


def test_no_transaction_files_run_outside_a_transaction(make_db: Callable[[], str], tmp_path: Path) -> None:
    write(tmp_path, "0001_table.sql", "CREATE TABLE big (i integer);")
    write(
        tmp_path,
        "0002_index.sql",
        "-- labtrack: no-transaction\n-- comment\nCREATE INDEX CONCURRENTLY big_i ON big (i);",
    )
    with connect(make_db()) as conn:
        assert migrate(conn, directory=tmp_path, log=quiet) == ["0001_table", "0002_index"]
        assert scalar(conn, "SELECT to_regclass('big_i')") == "big_i"


def test_no_transaction_files_hold_exactly_one_statement(make_db: Callable[[], str], tmp_path: Path) -> None:
    write(
        tmp_path,
        "0001_two.sql",
        "-- labtrack: no-transaction\nCREATE TABLE a (i integer);\nCREATE TABLE b (i integer);",
    )
    with connect(make_db()) as conn, pytest.raises(MigrationError, match="exactly one statement"):
        migrate(conn, directory=tmp_path, log=quiet)


def test_file_names_are_checked(tmp_path: Path) -> None:
    write(tmp_path, "1_short.sql", "SELECT 1;")
    with pytest.raises(MigrationError, match="are named 0001_short_name.sql"):
        load_migrations(tmp_path)
    (tmp_path / "1_short.sql").unlink()
    write(tmp_path, "0001_a.sql", "SELECT 1;")
    write(tmp_path, "0001_b.sql", "SELECT 2;")
    with pytest.raises(MigrationError, match="two files have version 0001"):
        load_migrations(tmp_path)


def test_line_endings_do_not_change_the_checksum(tmp_path: Path) -> None:
    """A Windows checkout (CRLF) must not look like an edited migration."""
    unix, windows = tmp_path / "unix", tmp_path / "windows"
    unix.mkdir()
    windows.mkdir()
    (unix / "0001_x.sql").write_bytes(b"CREATE TABLE x (i integer);\n-- done\n")
    (windows / "0001_x.sql").write_bytes(b"CREATE TABLE x (i integer);\r\n-- done\r\n")
    assert load_migrations(unix)[0].checksum == load_migrations(windows)[0].checksum


def test_the_repository_migrations_are_a_clean_sequence() -> None:
    migrations = load_migrations()
    assert [m.version for m in migrations] == list(range(1, len(migrations) + 1))
    assert [m.label for m in migrations if not m.transactional] == ["0012_recording_time_index"]


# ----------------------------------------------------------------------------------------------
# The migrations themselves
# ----------------------------------------------------------------------------------------------
def test_upgrading_a_database_that_already_has_data(make_db: Callable[[], str]) -> None:
    """The reason migrations exist: at version 7 there are sessions with their protocol only inside the JSON
    notes. Migrating on to the latest version must turn that into a real, validated, NOT NULL column."""
    with connect(make_db()) as conn:
        migrate(conn, target=7, log=quiet)
        conn.execute("""
            INSERT INTO lab.study (code, title, started_on, target_n) VALUES ('OLD-01', 'An older study', '2024-01-01', 5);
            INSERT INTO lab.researcher (full_name, role, email, hired_on) VALUES ('Old Timer', 'phd', 'old@lab.example', '2020-01-01');
            INSERT INTO lab.participant (code, birth_year, sex, dominant_hand, consent_signed_on)
                VALUES ('P0001', 1990, 'F', 'right', '2024-01-02'), ('P0002', 1991, 'M', 'left', '2024-01-02'), ('P0003', 1992, 'F', 'right', '2024-01-02');
            INSERT INTO lab.enrollment (study_id, participant_id, group_label, enrolled_on)
                SELECT study_id, participant_id, 'control', '2024-01-10' FROM lab.study, lab.participant;
            INSERT INTO lab.session (study_id, participant_id, researcher_id, visit_no, room, starts_at, ends_at, notes)
            SELECT 1, participant_id, 1, 1, 'R0' || participant_id, '2024-02-05 09:00-03', '2024-02-05 10:00-03',
                   CASE participant_id WHEN 1 THEN '{"protocol": "v3"}'::jsonb
                                       WHEN 2 THEN '{"protocol": "v2", "room_temp_c": 22.5}'::jsonb
                                       ELSE '{}'::jsonb END
            FROM lab.participant;
        """)
        assert not scalar(
            conn,
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'lab' "
            "AND table_name = 'session' AND column_name = 'protocol_version')",
        )
        migrate(conn, log=quiet)
        got = conn.execute("SELECT participant_id, protocol_version FROM lab.session ORDER BY 1").fetchall()
        assert got == [(1, "v3"), (2, "v2"), (3, "v1")]  # no note means the first protocol
        nullable, default = row(
            conn,
            "SELECT is_nullable, column_default FROM information_schema.columns "
            "WHERE table_schema = 'lab' AND table_name = 'session' AND column_name = 'protocol_version'",
        )
        assert nullable == "NO" and default == "'v2'::text"
        assert scalar(conn, "SELECT convalidated FROM pg_constraint WHERE conname = 'session_protocol_format'")


def test_the_validate_step_does_not_block_readers_or_writers(make_db: Callable[[], str]) -> None:
    """VALIDATE CONSTRAINT scans the table under SHARE UPDATE EXCLUSIVE, which lets reads and writes go on.
    Migration 0010 only ADDs the constraint, so the strong lock is gone by the time 0011 does the long scan."""
    with connect(make_db()) as conn:
        migrate(conn, target=10, log=quiet)
        with conn.transaction(force_rollback=True):
            conn.execute("ALTER TABLE lab.session VALIDATE CONSTRAINT session_protocol_format")
            modes = {
                r[0]
                for r in conn.execute(
                    "SELECT mode FROM pg_locks WHERE pid = pg_backend_pid() AND relation = 'lab.session'::regclass"
                )
            }
        assert "ShareUpdateExclusiveLock" in modes
        assert "AccessExclusiveLock" not in modes


def test_set_not_null_skips_its_own_scan_thanks_to_the_validated_check(make_db: Callable[[], str]) -> None:
    """PostgreSQL says so itself, at DEBUG1: the CHECK ... IS NOT NULL already proves the column has no NULLs."""
    messages: list[str] = []
    with connect(make_db()) as conn:
        migrate(conn, target=10, log=quiet)
        conn.add_notice_handler(lambda diag: messages.append(diag.message_primary or ""))
        with conn.transaction(force_rollback=True):
            conn.execute("ALTER TABLE lab.session VALIDATE CONSTRAINT session_protocol_format")
            conn.execute("SET LOCAL client_min_messages = debug1")
            conn.execute("ALTER TABLE lab.session ALTER COLUMN protocol_version SET NOT NULL")
    assert any("sufficient to prove that it does not contain nulls" in m for m in messages), messages
    assert not any(m.startswith('verifying table "session"') for m in messages), messages


def test_the_concurrent_index_exists_and_is_valid(migrated_dsn: str) -> None:
    with connect(migrated_dsn) as conn:
        valid = scalar(
            conn, "SELECT indisvalid FROM pg_index WHERE indexrelid = 'lab.recording_recorded_at_idx'::regclass"
        )
        assert valid


def test_roles_are_least_privilege(migrated_dsn: str) -> None:
    with connect(migrated_dsn) as conn:
        for role, may_write in (("labtrack_reader", False), ("labtrack_writer", True)):
            with conn.transaction(force_rollback=True):
                conn.execute(f"SET LOCAL ROLE {role}")
                conn.execute("SELECT count(*) FROM lab.study")  # both may read
                conn.execute("SELECT count(*) FROM bi.fact_session")
                if may_write:
                    conn.execute("DELETE FROM lab.trial_feature")  # the writer may write...
                else:
                    with pytest.raises(errors.InsufficientPrivilege), conn.transaction():
                        conn.execute("DELETE FROM lab.trial_feature")
        with conn.transaction(force_rollback=True):
            conn.execute("SET LOCAL ROLE labtrack_writer")
            with pytest.raises(errors.InsufficientPrivilege), conn.transaction():  # ...but not change the schema
                conn.execute("CREATE TABLE lab.sneaky (i integer)")
            with pytest.raises(errors.InsufficientPrivilege), conn.transaction():
                conn.execute("DROP TABLE lab.study")


def test_every_table_and_view_has_a_comment(migrated_dsn: str) -> None:
    """Documentation that lives in the database: \\d+ shows it, and docs/data-dictionary.md is generated from it."""
    with connect(migrated_dsn) as conn:
        no_comment = [
            f"{r[0]}.{r[1]}"
            for r in conn.execute(
                """SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname IN ('lab', 'bi') AND c.relkind IN ('r', 'v', 'm') AND obj_description(c.oid, 'pg_class') IS NULL
               ORDER BY 1, 2"""
            )
        ]
        assert no_comment == [], no_comment


def test_every_column_of_every_table_has_a_comment(migrated_dsn: str) -> None:
    """The data dictionary is generated from these comments, so a column without one is a hole in it."""
    with connect(migrated_dsn) as conn:
        no_comment = [
            f"{r[0]}.{r[1]}.{r[2]}"
            for r in conn.execute(
                """SELECT n.nspname, c.relname, a.attname
               FROM pg_attribute a
               JOIN pg_class c ON c.oid = a.attrelid
               JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname = 'lab' AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
                 AND col_description(c.oid, a.attnum) IS NULL
               ORDER BY 1, 2, a.attnum"""
            )
        ]
        assert no_comment == [], no_comment


def test_every_foreign_key_has_an_index_that_serves_it(migrated_dsn: str) -> None:
    """PostgreSQL indexes primary keys and UNIQUE columns, never the referencing side of a foreign key.
    Without an index that starts with the key's first column, deleting a parent row scans the child table."""
    with connect(migrated_dsn) as conn:
        unserved = [
            (r[0], r[1])
            for r in conn.execute(
                """SELECT c.conrelid::regclass::text, a.attname
               FROM pg_constraint c
               JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
               WHERE c.contype = 'f' AND c.connamespace = 'lab'::regnamespace
                 AND NOT EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = c.conrelid AND i.indkey[0] = c.conkey[1])
               ORDER BY 1, 2"""
            )
        ]
    # lab.trial_feature(feature_id) is left unindexed on purpose: explain-lab/01 builds that index.
    assert unserved == [("lab.trial_feature", "feature_id")], unserved


def test_project_root_finds_the_repository() -> None:
    assert (project_root() / "migrations").is_dir() and (project_root() / "seed").is_dir()
