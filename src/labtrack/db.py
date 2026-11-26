"""Connection helpers. One DSN, from --dsn, from $LABTRACK_DSN, or the docker-compose default."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import psycopg
from psycopg import conninfo, sql

DEFAULT_DSN = "postgresql://labtrack:labtrack@localhost:5432/labtrack"

Query = str | bytes | sql.SQL | sql.Composed          # what Connection.execute() accepts


def get_dsn(dsn: str | None = None) -> str:
    return dsn or os.environ.get("LABTRACK_DSN") or DEFAULT_DSN


def connect(dsn: str | None = None) -> psycopg.Connection:
    """An autocommit connection: callers open an explicit transaction when they want one."""
    return psycopg.connect(get_dsn(dsn), autocommit=True)


def with_dbname(dsn: str, dbname: str) -> str:
    """The same DSN, pointed at another database on the same server."""
    info = conninfo.conninfo_to_dict(dsn)
    info["dbname"] = dbname
    return conninfo.make_conninfo("", **info)


def row(conn: psycopg.Connection, query: Query, params: Sequence[Any] | None = None) -> tuple[Any, ...]:
    """The only row of a query that must return one (psycopg's fetchone() may also return None)."""
    found = conn.execute(query, params).fetchone()
    if found is None:
        text = query if isinstance(query, str) else repr(query)
        raise LookupError(f"the query returned no row: {' '.join(text.split())[:80]}")
    return found


def scalar(conn: psycopg.Connection, query: Query, params: Sequence[Any] | None = None) -> Any:
    """The first column of the only row of a query that must return one."""
    return row(conn, query, params)[0]


def project_root() -> Path:
    """The folder that holds migrations/, seed/, queries/ and explain-lab/.

    $LABTRACK_ROOT wins; otherwise the repository this package was installed from (pip install -e .),
    and as a last resort the current directory.
    """
    env = os.environ.get("LABTRACK_ROOT")
    if env:
        return Path(env)
    here = Path(__file__).resolve().parents[2]
    if (here / "migrations").is_dir():
        return here
    return Path.cwd()


def read_sql(path: Path) -> str:
    """Read a .sql file as UTF-8 and normalise line endings, so Windows checkouts behave the same."""
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")
