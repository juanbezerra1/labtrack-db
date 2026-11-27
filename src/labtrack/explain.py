"""The EXPLAIN lab: small lessons that show a query plan before and after a change.

A lesson file (explain-lab/NN_name.sql) is a header of comments followed by blocks:

    -- @explain LABEL     a SELECT that is run with EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
    -- @do                statements that are executed (CREATE INDEX, SET LOCAL ...), not explained
    -- @show LABEL        a SELECT whose result is printed (index sizes, say)
    -- @expect LABEL: Seq Scan | Bitmap     the plan of LABEL must contain one of these texts
    -- @forbid LABEL: Seq Scan              ... must contain none of them

Every lesson runs inside a transaction that is rolled back at the end: the lab never changes your data
or your indexes. (CREATE INDEX is transactional in PostgreSQL; CREATE INDEX CONCURRENTLY is not, so
lessons use the plain form.)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg

from .db import project_root, read_sql, row, scalar

MARKER = re.compile(r"^-- @(explain|do|show|expect|forbid)\b[ \t]*(.*)$", re.MULTILINE)
HEADER_TITLE = re.compile(r"^-- Lesson (\d+): (.+)$", re.MULTILINE)
HEADER_NEEDS = re.compile(r"^-- Needs: (\w+)", re.MULTILINE)
MIN_TRIAL_FEATURE_ROWS = {"tiny": 0, "small": 100_000, "medium": 800_000, "large": 8_000_000}


@dataclass(frozen=True)
class Step:
    kind: str  # explain | do | show
    label: str
    sql: str


@dataclass(frozen=True)
class Expectation:
    label: str
    forbid: bool
    alternatives: tuple[str, ...]


@dataclass(frozen=True)
class Lesson:
    number: int
    title: str
    needs: str
    intro: str
    path: Path
    steps: tuple[Step, ...]
    expectations: tuple[Expectation, ...]

    @property
    def stem(self) -> str:
        return self.path.stem


@dataclass
class ExplainResult:
    label: str
    sql: str
    nodes: list[dict[str, Any]]
    plan_text: str | None = None

    @property
    def root(self) -> dict[str, Any]:
        return self.nodes[0]

    @property
    def descriptions(self) -> list[str]:
        return [n["description"] for n in self.nodes]

    @property
    def execution_ms(self) -> float:
        return float(self.root["execution_ms"])

    def first(self, text: str) -> dict[str, Any]:
        for n in self.nodes:
            if text in n["description"]:
                return n
        raise KeyError(f"no plan node mentions {text!r}; the plan is: {self.descriptions}")


@dataclass
class LessonResult:
    lesson: Lesson
    explains: dict[str, ExplainResult] = field(default_factory=dict)
    shows: dict[str, tuple[list[str], list[tuple[Any, ...]]]] = field(default_factory=dict)


def load_lessons(directory: Path | None = None) -> list[Lesson]:
    lessons = []
    for path in sorted((directory or project_root() / "explain-lab").glob("*.sql")):
        text = read_sql(path)
        title = HEADER_TITLE.search(text)
        if not title:
            raise ValueError(f"{path.name}: the first line must be '-- Lesson NN: title'")
        needs = HEADER_NEEDS.search(text)
        pieces = MARKER.split(text)
        header = pieces[0]
        intro = "\n".join(
            line[3:] if line.startswith("-- ") else line[2:]
            for line in header.splitlines()[1:]
            if line.startswith("--") and not line.startswith("-- Needs:")
        ).strip()
        steps: list[Step] = []
        expectations: list[Expectation] = []
        for i in range(1, len(pieces), 3):
            kind, rest, body = pieces[i], pieces[i + 1].strip(), pieces[i + 2]
            if kind in ("expect", "forbid"):
                label, _, wanted = rest.partition(":")
                expectations.append(
                    Expectation(
                        label.strip(), kind == "forbid", tuple(w.strip() for w in wanted.split("|") if w.strip())
                    )
                )
            else:
                sql = "\n".join(line for line in body.splitlines() if not line.startswith("-- ")).strip()
                steps.append(Step(kind, rest or kind, sql))
        lessons.append(
            Lesson(
                int(title.group(1)),
                title.group(2),
                needs.group(1) if needs else "tiny",
                intro,
                path,
                tuple(steps),
                tuple(expectations),
            )
        )
    return lessons


def describe(node: dict[str, Any]) -> str:
    """One line in the style of psql's plan output: 'Index Scan using trial_pkey on trial'."""
    text: str = node["Node Type"]
    if node.get("Join Type") and node["Node Type"] in ("Hash Join", "Merge Join", "Nested Loop"):
        text += f" ({node['Join Type']})"
    if node.get("Index Name"):
        text += f" using {node['Index Name']}"
    if node.get("Relation Name"):
        text += f" on {node['Relation Name']}"
    if node["Node Type"] == "Sort" and node.get("Sort Method"):
        text += f" ({node['Sort Method']})"
    if node["Node Type"] == "Aggregate" and node.get("Strategy"):
        text += f" ({node['Strategy']})"
    if node.get("Parallel Aware"):
        text = "Parallel " + text if not text.startswith("Parallel") else text
    return text


def flatten(plan: dict[str, Any], top: dict[str, Any]) -> list[dict[str, Any]]:
    """The plan tree as a list, parents first, with the fields the lessons talk about."""
    nodes: list[dict[str, Any]] = []

    def walk(node: dict[str, Any], depth: int) -> None:
        nodes.append(
            {
                "depth": depth,
                "description": describe(node),
                "node_type": node["Node Type"],
                "estimated_rows": node.get("Plan Rows"),
                "actual_rows": node.get("Actual Rows"),
                "loops": node.get("Actual Loops"),
                "actual_ms": node.get("Actual Total Time"),
                "rows_removed_by_filter": node.get("Rows Removed by Filter"),
                "heap_fetches": node.get("Heap Fetches"),
                "sort_space_kb": node.get("Sort Space Used"),
                "shared_hit": node.get("Shared Hit Blocks"),
                "shared_read": node.get("Shared Read Blocks"),
                "workers_launched": node.get("Workers Launched"),
            }
        )
        for child in node.get("Plans", []):
            walk(child, depth + 1)

    walk(plan, 0)
    nodes[0]["execution_ms"] = top.get("Execution Time")
    nodes[0]["planning_ms"] = top.get("Planning Time")
    return nodes


def explain(conn: psycopg.Connection, sql: str, label: str, with_text: bool = False) -> ExplainResult:
    statement = sql.rstrip().rstrip(";")
    (document,) = row(conn, f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {statement}")
    result = ExplainResult(label, sql, flatten(document[0]["Plan"], document[0]))
    if with_text:
        rows = conn.execute(f"EXPLAIN (ANALYZE, BUFFERS) {statement}").fetchall()
        result.plan_text = "\n".join(r[0] for r in rows)
    return result


def scale_of(conn: psycopg.Connection) -> str:
    rows = int(scalar(conn, "SELECT count(*) FROM lab.trial_feature"))
    reached = "tiny"
    for name, minimum in MIN_TRIAL_FEATURE_ROWS.items():
        if rows >= minimum:
            reached = name
    return reached


def run_lesson(conn: psycopg.Connection, lesson: Lesson, with_text: bool = False) -> LessonResult:
    result = LessonResult(lesson)
    with conn.transaction(force_rollback=True):
        # 4MB is the PostgreSQL default, stated so that the lesson does not depend on the server's setting
        conn.execute("SET LOCAL work_mem = '4MB'")
        for step in lesson.steps:
            if step.kind == "do":
                conn.execute(step.sql)
            elif step.kind == "show":
                cur = conn.execute(step.sql)
                result.shows[step.label] = ([d.name for d in cur.description or []], cur.fetchall())
            else:
                result.explains[step.label] = explain(conn, step.sql, step.label, with_text)
    return result


def check_expectations(result: LessonResult) -> list[str]:
    """What the plans should look like: an empty list when everything is as the lesson says."""
    problems = []
    for exp in result.lesson.expectations:
        plan = result.explains.get(exp.label)
        if plan is None:
            problems.append(f"expectation refers to unknown step {exp.label!r}")
            continue
        found = [alt for alt in exp.alternatives if any(alt in d for d in plan.descriptions)]
        if exp.forbid and found:
            problems.append(f"{exp.label}: plan must not contain {found[0]!r}; plan is {plan.descriptions}")
        if not exp.forbid and not found:
            problems.append(
                f"{exp.label}: plan should contain one of {list(exp.alternatives)}; plan is {plan.descriptions}"
            )
    return problems


def render(result: LessonResult, plans: bool = False) -> str:
    lesson = result.lesson
    out = [f"Lesson {lesson.number}: {lesson.title}", "", lesson.intro, ""]
    for label, plan in result.explains.items():
        root = plan.root
        out.append(f"[{label}]  {root['execution_ms']:.1f} ms  (planning {root['planning_ms']:.1f} ms)")
        for n in plan.nodes:
            est, act = n["estimated_rows"], n["actual_rows"]
            extra = []
            if n["loops"] and n["loops"] > 1:
                extra.append(f"x{n['loops']} loops")
            if n["heap_fetches"] is not None:
                extra.append(f"heap fetches {n['heap_fetches']}")
            if n["rows_removed_by_filter"]:
                extra.append(f"{n['rows_removed_by_filter']:,} removed by filter")
            if n["sort_space_kb"]:
                extra.append(f"sort {n['sort_space_kb']:,} kB")
            tail = ("  " + ", ".join(extra)) if extra else ""
            out.append(f"  {'  ' * n['depth']}{n['description']}   rows: estimated {est:,}, actual {act:,}{tail}")
        hit, read = plan.root["shared_hit"], plan.root["shared_read"]
        out.append(f"  buffers: {hit:,} found in PostgreSQL's cache, {read:,} read in from the OS or disk")
        if plans and plan.plan_text:
            out += ["", *("    " + line for line in plan.plan_text.splitlines())]
        out.append("")
    for label, (columns, rows) in result.shows.items():
        from .queries import format_table

        out += [f"[{label}]", format_table(columns, rows), ""]
    problems = check_expectations(result)
    out.append("The plans are as the lesson says." if not problems else "NOT AS EXPECTED:\n  " + "\n  ".join(problems))
    return "\n".join(out)
