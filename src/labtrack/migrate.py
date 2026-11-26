"""A small migration runner: numbered .sql files, applied once each, in order, never edited later.

What it guarantees (the same things Flyway or sqitch promise, in ~150 lines):
  * each migration runs inside ONE transaction together with the row that records it, so it is
    either fully applied and recorded, or not applied at all;
  * a file that was changed after it was applied is an error (its checksum is stored);
  * two runners cannot work at the same time (an advisory lock);
  * a file marked "-- labtrack: no-transaction" holds exactly one statement and runs outside a
    transaction, which CREATE INDEX CONCURRENTLY requires.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import psycopg

from .db import project_root, read_sql, scalar

FILE_PATTERN = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
NO_TRANSACTION = "-- labtrack: no-transaction"
LOCK_KEY = 7_204_001  # an arbitrary number that identifies "a LabTrack migration is running"

TABLE_DDL = """
CREATE TABLE IF NOT EXISTS public.schema_migrations (
    version      integer     PRIMARY KEY,
    name         text        NOT NULL,
    checksum     text        NOT NULL,
    applied_at   timestamptz NOT NULL DEFAULT now(),
    execution_ms integer     NOT NULL
)
"""


class MigrationError(Exception):
    """Something about the migrations is wrong; the message says what and what to do."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path
    sql: str
    checksum: str

    @property
    def transactional(self) -> bool:
        return not self.sql.lstrip().startswith(NO_TRANSACTION)

    @property
    def label(self) -> str:
        return f"{self.version:04d}_{self.name}"


def load_migrations(directory: Path | None = None) -> list[Migration]:
    folder = directory or project_root() / "migrations"
    found: dict[int, Migration] = {}
    for path in sorted(folder.glob("*.sql")):
        match = FILE_PATTERN.match(path.name)
        if not match:
            raise MigrationError(f"{path.name}: migration files are named 0001_short_name.sql")
        version = int(match.group(1))
        if version in found:
            raise MigrationError(f"two files have version {version:04d}: {found[version].path.name} and {path.name}")
        sql = read_sql(path)
        found[version] = Migration(version, match.group(2), path, sql, hashlib.sha256(sql.encode()).hexdigest())
    return [found[v] for v in sorted(found)]


def _ensure_table(conn: psycopg.Connection) -> None:
    conn.execute(TABLE_DDL)


def _applied(conn: psycopg.Connection) -> dict[int, tuple[str, str]]:
    rows = conn.execute("SELECT version, name, checksum FROM public.schema_migrations").fetchall()
    return {int(v): (n, c) for v, n, c in rows}


def _check_history(migrations: list[Migration], applied: dict[int, tuple[str, str]]) -> None:
    by_version = {m.version: m for m in migrations}
    for version, (name, checksum) in sorted(applied.items()):
        m = by_version.get(version)
        if m is None:
            raise MigrationError(
                f"migration {version:04d}_{name} was applied but its file is gone; restore it from git"
            )
        if m.checksum != checksum:
            raise MigrationError(
                f"migration {m.label} was changed after it was applied. Never edit an applied "
                f"migration: undo your edit (git checkout) and write a new migration instead"
            )
    if applied:
        newest = max(applied)
        for m in migrations:
            if m.version < newest and m.version not in applied:
                raise MigrationError(
                    f"migration {m.label} is not applied but {newest:04d} is: it was added out of order"
                )


def status(conn: psycopg.Connection, directory: Path | None = None) -> list[dict[str, object]]:
    """One row per migration: applied, pending, or changed (applied, but the file differs now)."""
    migrations = load_migrations(directory)
    _ensure_table(conn)
    applied = _applied(conn)
    rows: list[dict[str, object]] = []
    for m in migrations:
        if m.version not in applied:
            state = "pending"
        elif applied[m.version][1] != m.checksum:
            state = "changed"
        else:
            state = "applied"
        rows.append({"version": m.version, "name": m.name, "state": state})
    return rows


def _single_statement(sql: str) -> str:
    body = "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--")).strip()
    if body.count(";") != 1 or not body.endswith(";"):
        raise MigrationError("a no-transaction migration must hold exactly one statement")
    return body


def migrate(
    conn: psycopg.Connection,
    target: int | None = None,
    directory: Path | None = None,
    log: Callable[[str], object] = print,
) -> list[str]:
    """Apply every pending migration (up to `target`), in order. Returns the labels applied."""
    migrations = load_migrations(directory)
    if not scalar(conn, "SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,)):
        raise MigrationError("another migration run is in progress (advisory lock is taken)")
    done: list[str] = []
    try:
        _ensure_table(conn)
        applied = _applied(conn)
        _check_history(migrations, applied)
        for m in migrations:
            if m.version in applied or (target is not None and m.version > target):
                continue
            started = time.perf_counter()
            if m.transactional:
                with conn.transaction():
                    conn.execute(m.sql)
                    _record(conn, m, started)
            else:
                conn.execute(_single_statement(m.sql))
                _record(conn, m, started)
            done.append(m.label)
            log(f"  applied {m.label}")
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
    return done


def _record(conn: psycopg.Connection, m: Migration, started: float) -> None:
    ms = int((time.perf_counter() - started) * 1000)
    conn.execute(
        "INSERT INTO public.schema_migrations (version, name, checksum, execution_ms) VALUES (%s, %s, %s, %s)",
        (m.version, m.name, m.checksum, ms),
    )
