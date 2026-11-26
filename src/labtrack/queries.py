"""The teaching queries in queries/*.sql.

A file holds one statement, or several "variants" that answer the same question in different ways, each
introduced by a line  -- @variant name. The test-suite checks that every variant of a file returns exactly
the same rows, and compares that result with a stored golden copy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

from .db import project_root, read_sql

VARIANT = re.compile(r"^-- @variant (\w+)[ \t]*$", re.MULTILINE)
TITLE = re.compile(r"^-- Query (\d+): (.+)$", re.MULTILINE)


@dataclass(frozen=True)
class Query:
    number: int
    title: str
    path: Path
    variants: tuple[tuple[str, str], ...]   # (name, sql)

    @property
    def stem(self) -> str:
        return self.path.stem


def load_queries(directory: Path | None = None) -> list[Query]:
    queries = []
    for path in sorted((directory or project_root() / "queries").glob("*.sql")):
        text = read_sql(path)
        title = TITLE.search(text)
        if not title:
            raise ValueError(f"{path.name}: the first line must be '-- Query NN: title'")
        parts = VARIANT.split(text)
        variants = (("default", text),) if len(parts) == 1 else tuple(
            (parts[i], parts[i + 1].strip()) for i in range(1, len(parts), 2))
        queries.append(Query(int(title.group(1)), title.group(2), path, variants))
    return queries


def run_query(conn: psycopg.Connection, sql: str, as_of: str = "2026-10-31") -> tuple[list[str], list[tuple[Any, ...]]]:
    """Run one statement the way the tests and the CLI do: lab calendar "today" fixed, stable time zone."""
    conn.execute("SELECT set_config('labtrack.as_of', %s, false)", (as_of,))
    conn.execute("SET TIME ZONE 'UTC'")
    cur = conn.execute(sql)
    columns = [d.name for d in cur.description or []]
    return columns, cur.fetchall()


def format_table(columns: list[str], rows: list[tuple[Any, ...]]) -> str:
    """A plain-text table, like psql prints."""
    cells = [[("" if v is None else str(v)) for v in row] for row in rows]
    widths = [max([len(c)] + [len(r[i]) for r in cells]) for i, c in enumerate(columns)]
    numeric = [all(isinstance(r[i], (int, float)) or r[i] is None or _is_number(r[i]) for r in rows) and bool(rows)
               for i in range(len(columns))]

    def line(values: list[str]) -> str:
        padded = (v.rjust(w) if numeric[i] else v.ljust(w) for i, (v, w) in enumerate(zip(values, widths, strict=True)))
        return " | ".join(padded).rstrip()

    out = [line(columns), "-+-".join("-" * w for w in widths)]
    out += [line(r) for r in cells]
    out.append(f"({len(rows)} row{'s' if len(rows) != 1 else ''})")
    return "\n".join(out)


def _is_number(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return not isinstance(value, bool)
