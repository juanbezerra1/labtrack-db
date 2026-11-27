"""Fill the database with synthetic, reproducible data by running the files in seed/.

The same scale and the same as-of date always give the same rows (see seed/01_reference.sql for how).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import psycopg

from .db import project_root, read_sql, scalar
from .migrate import MigrationError, load_migrations, status

SCALES: dict[str, int] = {"tiny": 20, "small": 60, "medium": 200, "large": 1800}
DEFAULT_AS_OF = "2026-10-31"

# Every table the seed fills, children first. feature_def is reference data loaded by a migration.
DATA_TABLES = [
    "trial_feature",
    "trial",
    "channel",
    "recording",
    "session_device",
    "session",
    "enrollment",
    "calibration",
    "device",
    "participant",
    "researcher",
    "study",
]


class SeedError(Exception):
    """The seed cannot run; the message says why and what to do."""


def seed_files(directory: Path | None = None) -> list[Path]:
    return sorted((directory or project_root() / "seed").glob("*.sql"))


def has_data(conn: psycopg.Connection) -> bool:
    return bool(scalar(conn, "SELECT EXISTS (SELECT 1 FROM lab.study)"))


def reset(conn: psycopg.Connection) -> None:
    """Delete every row the seed (or anyone) put in the data tables, and restart the id counters."""
    conn.execute("DROP SCHEMA IF EXISTS lab_seed CASCADE")
    conn.execute("TRUNCATE " + ", ".join(f"lab.{t}" for t in DATA_TABLES) + " RESTART IDENTITY")
    conn.execute("REFRESH MATERIALIZED VIEW lab.mv_monthly_throughput")


def seed(
    conn: psycopg.Connection,
    scale: str = "small",
    as_of: str = DEFAULT_AS_OF,
    do_reset: bool = False,
    directory: Path | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, int]:
    """Run the seed files in order, each in its own transaction. Returns the row count of every table."""
    if scale not in SCALES:
        raise SeedError(f"unknown scale {scale!r}; choose one of: {', '.join(SCALES)}")
    states = status(conn)
    changed = [f"{r['version']:04d}_{r['name']}" for r in states if r["state"] == "changed"]
    if changed:
        raise SeedError(
            f"migration {', '.join(changed)} was changed after it was applied; "
            "recreate the database, or undo the edit (see labtrack status)"
        )
    if any(r["state"] == "pending" for r in states):
        raise SeedError("the database is not at the latest migration; run: labtrack migrate")
    if has_data(conn):
        if not do_reset:
            raise SeedError("the database already has data; add --reset to delete it first")
        log("  reset: deleting existing data")
        reset(conn)
    files = seed_files(directory)
    if not files:
        raise SeedError("no seed files found (looked for seed/*.sql); set LABTRACK_ROOT to the repository folder")

    conn.execute("DROP SCHEMA IF EXISTS lab_seed CASCADE")
    conn.execute("SELECT set_config('labtrack.seed_participants', %s, false)", (str(SCALES[scale]),))
    conn.execute("SELECT set_config('labtrack.seed_as_of', %s, false)", (as_of,))
    total = time.perf_counter()
    for path in files:
        started = time.perf_counter()
        try:
            with conn.transaction():
                conn.execute(read_sql(path))
        except psycopg.Error as exc:
            conn.execute("DROP SCHEMA IF EXISTS lab_seed CASCADE")
            raise SeedError(f"{path.name} failed: {exc}") from exc
        log(f"  {path.name:<22} {time.perf_counter() - started:6.1f} s")
    started = time.perf_counter()
    conn.execute("VACUUM (ANALYZE)")  # needs autocommit: it cannot run inside a transaction block
    log(f"  {'VACUUM (ANALYZE)':<22} {time.perf_counter() - started:6.1f} s")
    log(f"  total {time.perf_counter() - total:.1f} s")
    return counts(conn)


def counts(conn: psycopg.Connection) -> dict[str, int]:
    result: dict[str, int] = {}
    for table in reversed(DATA_TABLES):
        result[table] = int(scalar(conn, f"SELECT count(*) FROM lab.{table}"))
    return result


__all__ = ["DEFAULT_AS_OF", "SCALES", "SeedError", "MigrationError", "load_migrations", "seed", "reset", "counts"]
