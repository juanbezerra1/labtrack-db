"""The data dictionary (docs/data-dictionary.md), generated from the database catalog.

The comments written with COMMENT ON in the migrations are the single source: this module only formats
them, together with each column's type, nullability and default, and each table's constraints and indexes.
A test fails when the committed file differs from what this produces, so documentation cannot drift.
"""

from __future__ import annotations

import psycopg

TABLES = """
SELECT n.nspname, c.relname, c.relkind::text, c.oid, obj_description(c.oid, 'pg_class')
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname IN ('lab', 'bi') AND c.relkind IN ('r', 'v', 'm')
ORDER BY n.nspname DESC, CASE c.relkind WHEN 'r' THEN 1 WHEN 'm' THEN 2 ELSE 3 END, c.relname
"""

COLUMNS = """
SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
       CASE WHEN a.attgenerated = 's' THEN 'generated: ' || pg_get_expr(d.adbin, d.adrelid)
            WHEN a.attidentity <> '' THEN 'identity'
            ELSE pg_get_expr(d.adbin, d.adrelid) END,
       col_description(a.attrelid, a.attnum)
FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
WHERE a.attrelid = %s AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY a.attnum
"""

CONSTRAINTS = """
SELECT conname, pg_get_constraintdef(oid, true) FROM pg_constraint WHERE conrelid = %s ORDER BY contype, conname
"""

INDEXES = """
SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = %s AND tablename = %s ORDER BY indexname
"""

KINDS = {"r": "table", "v": "view", "m": "materialized view"}


def _cell(text: object) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def generate(conn: psycopg.Connection) -> str:
    out = [
        "# Data dictionary",
        "",
        "Generated from the database by `labtrack dictionary`; do not edit by hand. The descriptions are the",
        "`COMMENT ON` statements of the migrations.",
        "",
    ]
    for schema, name, kind, oid, comment in conn.execute(TABLES).fetchall():
        out += [f"## {schema}.{name}", "", f"*{KINDS[kind]}.* {comment or ''}".rstrip(), ""]
        out += ["| column | type | null | default | description |", "|---|---|---|---|---|"]
        for col, typ, notnull, default, desc in conn.execute(COLUMNS, (oid,)).fetchall():
            nullable = "" if (notnull or kind != "r") else "yes"
            out.append(f"| `{col}` | {_cell(typ)} | {nullable} | {_cell(default)} | {_cell(desc)} |")
        out.append("")
        if kind == "r":
            constraints = conn.execute(CONSTRAINTS, (oid,)).fetchall()
            if constraints:
                out += ["Constraints:", ""] + [f"- `{n}`: `{_cell(d)}`" for n, d in constraints] + [""]
        if kind in ("r", "m"):
            indexes = conn.execute(INDEXES, (schema, name)).fetchall()
            if indexes:
                out += ["Indexes:", ""] + [f"- `{n}`: `{_cell(d)}`" for n, d in indexes] + [""]
    return "\n".join(out).rstrip() + "\n"
