"""CSV export of the star schema (the bi views), for tools that read files: Power BI, Excel, pandas.

The files are plain UTF-8 with LF line endings, a header row, booleans spelled true/false, no thousands
separators, dates as YYYY-MM-DD. The same database always produces byte-identical files, which is how the
tests know nothing drifted.
"""

from __future__ import annotations

import csv
import hashlib
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg

EXPORT_VIEWS = [
    "dim_date", "dim_study", "dim_participant", "dim_researcher", "dim_device",
    "fact_session", "fact_recording", "fact_trial",
]


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        return repr(value)
    return str(value)


def export_csv(conn: psycopg.Connection, directory: Path) -> dict[str, int]:
    """Write one CSV per view into `directory` plus SHA256SUMS; returns the number of rows of each file."""
    directory.mkdir(parents=True, exist_ok=True)
    conn.execute("SET TIME ZONE 'UTC'")
    counts: dict[str, int] = {}
    sums: list[str] = []
    for view in EXPORT_VIEWS:
        cur = conn.execute(f"SELECT * FROM bi.{view} ORDER BY 1")
        header = [d.name for d in cur.description or []]
        rows = cur.fetchall()
        path = directory / f"{view}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(header)
            writer.writerows([_cell(v) for v in row] for row in rows)
        counts[view] = len(rows)
        sums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    (directory / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8", newline="\n")
    return counts
