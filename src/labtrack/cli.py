"""Command line: python -m labtrack <command> (or the `labtrack` script after pip install -e .)."""

from __future__ import annotations

import argparse
import sys

import psycopg
from psycopg import sql

from . import __version__
from .checks import run_checks
from .db import connect, get_dsn, with_dbname
from .dictionary import generate as generate_dictionary
from .explain import check_expectations, load_lessons, render, run_lesson, scale_of
from .exports import export_csv
from .migrate import MigrationError, migrate, status
from .queries import format_table, load_queries, run_query
from .seed import DEFAULT_AS_OF, SCALES, SeedError, counts, seed


def _cmd_createdb(args: argparse.Namespace) -> int:
    """Create the database named in the DSN if it is not there (connects to 'postgres' to do it)."""
    info = psycopg.conninfo.conninfo_to_dict(get_dsn(args.dsn))
    name = str(info.get("dbname") or "labtrack")
    with psycopg.connect(with_dbname(get_dsn(args.dsn), "postgres"), autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if exists:
            print(f"database {name!r} already exists")
        else:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            print(f"created database {name!r}")
    return 0


def _cmd_migrate(args: argparse.Namespace) -> int:
    with connect(args.dsn) as conn:
        done = migrate(conn, target=args.to)
    print(f"{len(done)} migration(s) applied" if done else "nothing to apply: the database is up to date")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    with connect(args.dsn) as conn:
        rows = status(conn)
    for r in rows:
        print(f"  {r['version']:04d}  {r['state']:<8}  {r['name']}")
    return 1 if any(r["state"] == "changed" for r in rows) else 0


def _cmd_seed(args: argparse.Namespace) -> int:
    with connect(args.dsn) as conn:
        print(f"seeding scale {args.scale!r} ({SCALES[args.scale]} participants), as of {args.as_of}")
        result = seed(conn, scale=args.scale, as_of=args.as_of, do_reset=args.reset)
    for table, n in result.items():
        print(f"  {table:<15} {n:>10,}")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    with connect(args.dsn) as conn:
        results = run_checks(conn)
    failed = 0
    for check, n in results:
        mark = "ok  " if n == 0 else "FAIL"
        print(f"  {mark} {check.name:<30} {check.rule if n else ''}{'' if n == 0 else f'  ({n} rows)'}")
        failed += n != 0
    print(f"{len(results) - failed} of {len(results)} checks passed")
    return 1 if failed else 0


def _cmd_query(args: argparse.Namespace) -> int:
    queries = load_queries()
    if args.number is None:
        for q in queries:
            names = ", ".join(n for n, _ in q.variants) if len(q.variants) > 1 else ""
            print(f"  {q.number:>2}  {q.title}" + (f"   [variants: {names}]" if names else ""))
        print("\nrun one with:  labtrack query NUMBER   (add --show to print the SQL)")
        return 0
    chosen = [q for q in queries if q.number == args.number]
    if not chosen:
        print(f"error: there is no query number {args.number}; run 'labtrack query' to list them", file=sys.stderr)
        return 1
    query = chosen[0]
    variants = [v for v in query.variants if args.variant in (None, v[0])]
    if not variants:
        print(f"error: query {query.number} has no variant {args.variant!r}", file=sys.stderr)
        return 1
    with connect(args.dsn) as conn:
        for name, sql in variants:
            suffix = f"  [variant {name}]" if len(query.variants) > 1 else ""
            print(f"-- Query {query.number}: {query.title}{suffix}")
            if args.show:
                print(sql.rstrip())
                print()
            columns, rows = run_query(conn, sql, as_of=args.as_of)
            print(format_table(columns, rows))
            print()
    return 0


def _cmd_explain_lab(args: argparse.Namespace) -> int:
    lessons = load_lessons()
    if args.number is None:
        for lesson in lessons:
            print(f"  {lesson.number:>2}  {lesson.title}   (needs the {lesson.needs} scale or larger)")
        print("\nrun one with:  labtrack explain-lab NUMBER   (add --plans for PostgreSQL's own text output)")
        return 0
    chosen = [lesson for lesson in lessons if lesson.number == args.number]
    if not chosen:
        print(f"error: there is no lesson {args.number}; run 'labtrack explain-lab' to list them", file=sys.stderr)
        return 1
    with connect(args.dsn) as conn:
        have = scale_of(conn)
        order = list(SCALES)
        if have == "tiny" or order.index(have) < order.index(chosen[0].needs):
            print(f"warning: this lesson needs the {chosen[0].needs} scale; the database looks like {have}. "
                  "On small tables the planner picks other plans.\n"
                  f"(labtrack seed --scale {chosen[0].needs} --reset)\n")
        result = run_lesson(conn, chosen[0], with_text=args.plans)
    print(render(result, plans=args.plans))
    return 1 if check_expectations(result) else 0


def _cmd_export(args: argparse.Namespace) -> int:
    from pathlib import Path
    with connect(args.dsn) as conn:
        counts_by_file = export_csv(conn, Path(args.out))
    for name, n in counts_by_file.items():
        print(f"  {name + '.csv':<22} {n:>8,} rows")
    print(f"written to {args.out} (with SHA256SUMS)")
    return 0


def _cmd_dictionary(args: argparse.Namespace) -> int:
    with connect(args.dsn) as conn:
        text = generate_dictionary(conn)
    if args.out:
        from pathlib import Path
        Path(args.out).write_text(text, encoding="utf-8", newline="\n")
        print(f"written to {args.out}")
    else:
        sys.stdout.write(text)
    return 0


def _cmd_counts(args: argparse.Namespace) -> int:
    with connect(args.dsn) as conn:
        for table, n in counts(conn).items():
            print(f"  {table:<15} {n:>10,}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="labtrack", description="LabTrack: PostgreSQL schema, migrations, seed and EXPLAIN lab.")
    ap.add_argument("--version", action="version", version=f"labtrack {__version__}")
    ap.add_argument("--dsn", help="connection string (default: $LABTRACK_DSN or the docker-compose database)")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("createdb", help="create the database from the DSN if it does not exist")
    p.set_defaults(func=_cmd_createdb)
    p = sub.add_parser("migrate", help="apply the pending migrations")
    p.add_argument("--to", type=int, help="stop after this version (default: apply all)")
    p.set_defaults(func=_cmd_migrate)
    p = sub.add_parser("status", help="list the migrations and whether each one is applied")
    p.set_defaults(func=_cmd_status)
    p = sub.add_parser("seed", help="fill the database with synthetic, reproducible data")
    p.add_argument("--scale", choices=list(SCALES), default="small",
                   help="tiny 20, small 60, medium 200, large 1800 participants")
    p.add_argument("--as-of", default=DEFAULT_AS_OF, help="the seed's 'today' (default %(default)s)")
    p.add_argument("--reset", action="store_true", help="delete existing data first")
    p.set_defaults(func=_cmd_seed)
    p = sub.add_parser("check", help="run the data-quality checks (each must find nothing)")
    p.set_defaults(func=_cmd_check)
    p = sub.add_parser("query", help="list the teaching queries, or run one")
    p.add_argument("number", nargs="?", type=int, help="the query number (omit to list them)")
    p.add_argument("--variant", help="run only this variant")
    p.add_argument("--show", action="store_true", help="print the SQL before the result")
    p.add_argument("--as-of", default=DEFAULT_AS_OF,
                   help="what 'today' means for the lab's views (default %(default)s)")
    p.set_defaults(func=_cmd_query)
    p = sub.add_parser("explain-lab", help="list the EXPLAIN lessons, or run one (it changes nothing: it rolls back)")
    p.add_argument("number", nargs="?", type=int, help="the lesson number (omit to list them)")
    p.add_argument("--plans", action="store_true", help="also print PostgreSQL's own EXPLAIN text for each step")
    p.set_defaults(func=_cmd_explain_lab)
    p = sub.add_parser("export", help="write the star schema (bi views) as CSV files for Power BI, Excel or pandas")
    p.add_argument("--out", default="exports/export", help="folder to write into (default %(default)s)")
    p.set_defaults(func=_cmd_export)
    p = sub.add_parser("dictionary", help="print (or write with --out) the data dictionary generated from the catalog")
    p.add_argument("--out", help="write to this file instead of printing")
    p.set_defaults(func=_cmd_dictionary)
    p = sub.add_parser("counts", help="row count of every data table")
    p.set_defaults(func=_cmd_counts)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (MigrationError, SeedError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as exc:
        print(f"error: could not connect to the database: {str(exc).strip()}\n"
              f"       (DSN: {_safe_dsn(get_dsn(args.dsn))}; see the README, section Quick start)", file=sys.stderr)
        return 1


def _safe_dsn(dsn: str) -> str:
    """The DSN without the password, for error messages."""
    info = psycopg.conninfo.conninfo_to_dict(dsn)
    info.pop("password", None)
    return psycopg.conninfo.make_conninfo("", **info)
