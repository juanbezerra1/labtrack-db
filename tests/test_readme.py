"""The README says things about the database. These tests make the README answer to the database: the diagram,
the tables of numbers and every `$ labtrack ...` transcript are compared with the real thing, in both
languages, so the documentation cannot drift away from the code without a red build.

When one fails, the message says what differs. The fix is usually to run the command and paste its output
into the README (or to edit the table), not to change the test."""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

import pytest

from labtrack.checks import CHECKS
from labtrack.cli import build_parser, main
from labtrack.db import connect, project_root, scalar
from labtrack.explain import load_lessons
from labtrack.migrate import load_migrations
from labtrack.queries import load_queries, run_query
from labtrack.seed import SCALES

ROOT = project_root()
LANGS = ("en", "pt")
README = {"en": ROOT / "README.md", "pt": ROOT / "README.pt-BR.md"}
DESIGN_NOTES = ROOT / "docs" / "design-notes.md"
MEASUREMENTS = ROOT / "docs" / "measurements" / "explain-lab-large.json"

TITLES = {
    "en": {"glance": "At a glance", "schema": "The schema", "sizes": "Sizes", "planted": "What is planted in the data",
           "queries": "Teaching queries", "lab": "EXPLAIN lab", "bi": "Dashboards", "cli": "Command line",
           "layout": "Repository layout"},
    "pt": {"glance": "Visão geral", "schema": "O esquema", "sizes": "Tamanhos", "planted": "O que foi plantado nos dados",
           "queries": "Consultas didáticas", "lab": "Laboratório de EXPLAIN", "bi": "Dashboards",
           "cli": "Linha de comando", "layout": "Estrutura do repositório"},
}

FENCE = re.compile(r"^```(\w*)\n(.*?)^```$", re.MULTILINE | re.DOTALL)


# ---- reading Markdown -------------------------------------------------------------------------
def read(lang: str) -> str:
    return README[lang].read_text(encoding="utf-8").replace("\r\n", "\n")


def fenced(text: str, kind: str) -> list[str]:
    """The bodies of the code blocks of one kind (```console, ```mermaid, ...)."""
    return [body for info, body in FENCE.findall(text) if info == kind]


def without_code(text: str) -> str:
    return FENCE.sub("", text)


def section(text: str, title: str) -> str:
    found = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert found, f"there is no section '## {title}'"
    return found.group(1)


def tables(markdown: str) -> list[tuple[list[str], list[list[str]]]]:
    """Every Markdown table outside code blocks, as (header cells, body rows)."""
    found: list[tuple[list[str], list[list[str]]]] = []
    current: list[list[str]] = []
    for line in [*without_code(markdown).splitlines(), ""]:
        if line.startswith("|"):
            current.append([cell.strip() for cell in line.strip().strip("|").split("|")])
        elif current:
            found.append((current[0], current[2:]))
            current = []
    return found


def first_table(text: str, title: str) -> list[list[str]]:
    found = tables(section(text, title))
    assert found, f"no table in the section '{title}'"
    return found[0][1]


def number(cell: str, lang: str) -> float:
    """A number as the README writes it: 1,234.5 in English and 1.234,5 in Portuguese; '< 0.1' counts as 0."""
    cell = cell.replace("`", "").strip()
    if cell.startswith("<"):
        return 0.0
    cell = cell.replace(".", "").replace(",", ".") if lang == "pt" else cell.replace(",", "")
    return float(cell)


def normalise(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip("\n").splitlines())


def slug(heading: str) -> str:
    """The anchor GitHub makes from a heading."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def anchors(markdown: str) -> set[str]:
    return {slug(found.group(1)) for found in re.finditer(r"^#{1,6} (.+)$", without_code(markdown), re.MULTILINE)}


# ---- what the database says -------------------------------------------------------------------
@dataclass(frozen=True)
class Catalog:
    tables: set[str]
    columns: dict[str, set[str]]
    primary_keys: dict[str, set[str]]
    single_unique: dict[str, set[str]]
    foreign_keys: list[tuple[str, str, tuple[str, ...]]]      # (child table, parent table, child columns)
    constraint_names: set[str]
    enum_types: int
    trigger_source: str


CONSTRAINTS_SQL = """
SELECT cl.relname, c.contype::text, c.conname, fcl.relname,
       (SELECT array_agg(a.attname ORDER BY k.ord)
        FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum)
FROM pg_constraint c
JOIN pg_class cl ON cl.oid = c.conrelid
JOIN pg_namespace n ON n.oid = cl.relnamespace
LEFT JOIN pg_class fcl ON fcl.oid = c.confrelid
WHERE n.nspname = 'lab'
"""


@pytest.fixture(scope="module")
def catalog(migrated_dsn: str) -> Catalog:
    with connect(migrated_dsn) as conn:
        tables_ = {r[0] for r in conn.execute(
            "SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'lab' AND c.relkind = 'r'")}
        columns: dict[str, set[str]] = {t: set() for t in tables_}
        for table, column in conn.execute(
                "SELECT c.relname, a.attname FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'lab' AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped"):
            columns[table].add(column)
        primary_keys: dict[str, set[str]] = {}
        single_unique: dict[str, set[str]] = {}
        foreign_keys: list[tuple[str, str, tuple[str, ...]]] = []
        names: set[str] = set()
        for table, kind, name, parent, cols in conn.execute(CONSTRAINTS_SQL):
            names.add(name)
            if kind == "p":
                primary_keys[table] = set(cols)
            elif kind == "u" and len(cols) == 1:
                single_unique.setdefault(table, set()).add(cols[0])
            elif kind == "f":
                foreign_keys.append((table, parent, tuple(cols)))
        enums = scalar(conn, "SELECT count(*) FROM pg_type WHERE typtype = 'e' AND typnamespace = 'lab'::regnamespace")
        source = scalar(conn, "SELECT pg_get_functiondef('lab.session_rules'::regproc)")
    return Catalog(tables_, columns, primary_keys, single_unique, foreign_keys, names, int(enums), str(source))


# ---- the diagram ------------------------------------------------------------------------------
ENTITY = re.compile(r"^ {4}(\w+) \{$")
ATTRIBUTE = re.compile(r'^ {8}(\S+) (\w+)(?: ((?:PK|FK|UK)(?:, (?:PK|FK|UK))*))?(?: "[^"]*")?$')
RELATION = re.compile(r'^ {4}(\w+) \|\|--o\{ (\w+) : "[^"]*"$')


def parse_diagram(source: str) -> tuple[dict[str, dict[str, set[str]]], list[tuple[str, str]]]:
    """The entities (name -> column -> keys) and the relationships (parent, child) of a Mermaid erDiagram."""
    entities: dict[str, dict[str, set[str]]] = {}
    relationships: list[tuple[str, str]] = []
    current: str | None = None
    for line in source.splitlines():
        if not line.strip() or line == "erDiagram":
            continue
        if found := RELATION.match(line):
            relationships.append((found.group(1), found.group(2)))
        elif found := ENTITY.match(line):
            current = found.group(1)
            entities[current] = {}
        elif line == "    }":
            current = None
        elif current and (found := ATTRIBUTE.match(line)):
            entities[current][found.group(2)] = set((found.group(3) or "").replace(",", "").split())
        else:
            pytest.fail(f"cannot read this line of the diagram: {line!r}")
    return entities, relationships


def marked(attributes: dict[str, set[str]], key: str) -> set[str]:
    """The columns of one diagram entity that carry a key marker (PK, FK or UK)."""
    return {column for column, keys in attributes.items() if key in keys}


@pytest.mark.parametrize("lang", LANGS)
def test_the_er_diagram_matches_the_catalog(lang: str, catalog: Catalog) -> None:
    diagrams = fenced(read(lang), "mermaid")
    assert len(diagrams) == 1, "the README should have exactly one diagram"
    entities, relationships = parse_diagram(diagrams[0])
    assert set(entities) == catalog.tables, "the diagram must draw every table of schema lab and nothing else"
    assert sorted((child, parent) for parent, child in relationships) == sorted(
        (child, parent) for child, parent, _ in catalog.foreign_keys), "the arrows must be the foreign keys"
    for table, attributes in entities.items():
        unknown = set(attributes) - catalog.columns[table]
        assert not unknown, f"{table}: the diagram draws columns that do not exist: {sorted(unknown)}"
        foreign = {c for child, _, cols in catalog.foreign_keys if child == table for c in cols}
        assert marked(attributes, "PK") == catalog.primary_keys[table], f"{table}: primary key"
        assert marked(attributes, "FK") == foreign, f"{table}: foreign key columns"
        assert marked(attributes, "UK") == catalog.single_unique.get(table, set()), f"{table}: single-column unique keys"


# ---- the numbers ------------------------------------------------------------------------------
@pytest.mark.parametrize("lang", LANGS)
def test_the_numbers_at_a_glance_are_true(lang: str, catalog: Catalog) -> None:
    rows = first_table(read(lang), TITLES[lang]["glance"])
    expected = [len(catalog.tables), len(catalog.foreign_keys), catalog.enum_types, len(load_migrations()),
                len(load_queries()), len(load_lessons()), len(CHECKS), len(SCALES)]
    assert [int(number(row[1], lang)) for row in rows] == expected


@pytest.mark.parametrize("lang", LANGS)
def test_the_table_of_sizes_matches_the_pinned_counts(lang: str) -> None:
    rows = first_table(read(lang), TITLES[lang]["sizes"])
    shown = {row[0].strip("`"): [number(cell, lang) for cell in row[1:6]] for row in rows}
    assert list(shown) == list(SCALES)
    assert [values[0] for values in shown.values()] == list(SCALES.values())
    keys = ["participant", "session", "recording", "trial", "trial_feature"]
    for scale in ("tiny", "small", "medium"):
        golden = json.loads((ROOT / "tests" / "golden" / f"seed_counts_{scale}.json").read_text(encoding="utf-8"))
        assert shown[scale] == [golden[key] for key in keys], f"{scale}: run labtrack counts and fix the table"
    # large is measured once, not pinned: it only has to be bigger than medium
    assert all(big > small for big, small in zip(shown["large"], shown["medium"], strict=True))


@pytest.mark.parametrize("lang", LANGS)
def test_the_table_of_queries_matches_the_query_files(lang: str) -> None:
    rows = first_table(read(lang), TITLES[lang]["queries"])
    queries = load_queries()
    assert [int(row[0]) for row in rows] == [q.number for q in queries]
    for row, query in zip(rows, queries, strict=True):
        listed = [name.strip("` ") for name in row[3].split(",") if name.strip()]
        assert listed == ([name for name, _ in query.variants] if len(query.variants) > 1 else []), query.stem
        if lang == "en":
            assert row[1] == query.title, f"query {query.number}: the title in the README differs from the file"


@pytest.mark.parametrize("lang", LANGS)
def test_the_table_of_lessons_matches_the_lesson_files_and_the_measurements(lang: str) -> None:
    rows = first_table(read(lang), TITLES[lang]["lab"])
    lessons = load_lessons()
    measured = json.loads(MEASUREMENTS.read_text(encoding="utf-8"))["lessons"]
    assert [int(row[0]) for row in rows] == [lesson.number for lesson in lessons]
    for row, lesson in zip(rows, lessons, strict=True):
        shown = [number(cell, lang) for cell in re.findall(r"<\s*0[.,]1|\d[\d.,]*", row[2])]
        steps = [step["median_ms"] for step in measured[str(lesson.number)]["steps"].values()]
        assert shown == steps, f"lesson {lesson.number}: the README and {MEASUREMENTS.name} disagree"
        if lang == "en":
            assert row[1] == lesson.title, f"lesson {lesson.number}: the title in the README differs from the file"


def grouped(value: int, lang: str) -> str:
    return f"{value:,}" if lang == "en" else f"{value:,}".replace(",", ".")


@pytest.mark.parametrize("lang", LANGS)
def test_the_description_of_the_measurement_matches_the_json(lang: str) -> None:
    text = read(lang)
    data = json.loads(MEASUREMENTS.read_text(encoding="utf-8"))
    assert data["scale"] == "large"
    memory = str(data["machine"]["memory_gib"])
    assert f"{data['machine']['cpus']} vCPUs" in text
    assert f"{memory if lang == 'en' else memory.replace('.', ',')} GiB" in text
    found = re.search(r"PostgreSQL (\d+\.\d+)", data["server"]["version"])
    assert found and f"PostgreSQL {found.group(1)}" in text
    assert grouped(data["trial_feature_rows"], lang) in text
    assert f"{data['runs_per_lesson']} {'runs' if lang == 'en' else 'execuções'}" in text
    for setting in ("shared_buffers", "work_mem"):
        assert data["server"]["settings"][setting].replace("MB", " MB") in text, setting


@pytest.mark.parametrize("lang", LANGS)
def test_the_table_of_exports_matches_the_committed_csv_files(lang: str) -> None:
    rows = first_table(read(lang), TITLES[lang]["bi"])
    folder = ROOT / "exports" / "small"
    assert {row[0].strip("`") for row in rows} == {path.name for path in folder.glob("*.csv")}
    for row in rows:
        with (folder / row[0].strip("`")).open(encoding="utf-8", newline="") as handle:
            assert sum(1 for _ in csv.reader(handle)) - 1 == int(number(row[1], lang)), row[0]


@pytest.mark.parametrize("lang", LANGS)
def test_the_table_of_commands_is_the_list_of_commands(lang: str) -> None:
    rows = first_table(read(lang), TITLES[lang]["cli"])
    shown = []
    for row in rows:
        found = re.match(r"`labtrack (\S+)`", row[0])
        assert found, row[0]
        shown.append(found.group(1))
    action = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))
    assert shown == list(action.choices)


@pytest.mark.parametrize("lang", LANGS)
def test_the_repository_layout_lists_what_is_there(lang: str) -> None:
    block = fenced(section(read(lang), TITLES[lang]["layout"]), "text")[0]
    listed = {line.split()[0].rstrip("/") for line in block.splitlines() if line.strip()}
    ignored = {"build", "dist", "venv", "env", "__pycache__"}
    actual = {p.name for p in ROOT.iterdir()
              if not p.name.startswith(".") and p.name not in ignored and not p.name.endswith(".egg-info")}
    assert listed == actual


# ---- the transcripts --------------------------------------------------------------------------
def run_cli(dsn: str, args: list[str]) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(["--dsn", dsn, *args])
    assert code == 0, f"labtrack {' '.join(args)} exited with {code}"
    return normalise(buffer.getvalue())


@pytest.mark.parametrize("lang", LANGS)
def test_every_transcript_is_what_the_tool_prints(lang: str, small_dsn: str) -> None:
    transcripts = fenced(read(lang), "console")
    assert len(transcripts) >= 4
    for block in transcripts:
        first, _, shown = block.partition("\n")
        assert first.startswith("$ labtrack "), first
        actual = run_cli(small_dsn, shlex.split(first[len("$ labtrack "):]))
        assert actual == normalise(shown), f"the output of '{first}' changed: paste the new output into the README"


def test_the_portuguese_readme_follows_the_english_one() -> None:
    en, pt = read("en"), read("pt")

    def levels(text: str) -> list[int]:
        return [len(found.group(1)) for found in re.finditer(r"^(#{2,3}) ", without_code(text), re.MULTILINE)]

    assert levels(en) == levels(pt), "the two READMEs have different sections"
    assert [info for info, _ in FENCE.findall(en)] == [info for info, _ in FENCE.findall(pt)]
    for kind in ("console", "mermaid"):
        assert fenced(en, kind) == fenced(pt, kind), f"the {kind} blocks must be identical in both languages"
    assert [len(rows) for _, rows in tables(en)] == [len(rows) for _, rows in tables(pt)]


# ---- what the planted-data section promises ----------------------------------------------------
@pytest.mark.parametrize("lang", LANGS)
def test_the_device_table_matches_the_device_status_view(lang: str, small_dsn: str) -> None:
    rows = first_table(read(lang), TITLES[lang]["planted"])
    stated = {serial: row[2].strip("`") for row in rows for serial in re.findall(r"SN-[A-Z]+-\d+", row[0])}
    with connect(small_dsn) as conn:
        conn.execute("SET labtrack.as_of = '2026-10-31'")
        actual: dict[str, str] = dict(
            conn.execute("SELECT serial_no, calibration_status FROM lab.v_device_status").fetchall())
    for serial, status in stated.items():
        assert actual[serial] == status, serial
    assert {serial for serial, status in actual.items() if status != "ok"} <= set(stated)


@pytest.mark.parametrize("dsn_fixture", ["small_dsn", "medium_dsn"])
@pytest.mark.parametrize("lang", LANGS)
def test_query_4_finds_the_devices_that_skipped_calibration_rounds(
        lang: str, dsn_fixture: str, request: pytest.FixtureRequest) -> None:
    skipped = set(re.findall(r"SN-[A-Z]+-\d+", first_table(read(lang), TITLES[lang]["planted"])[0][0]))
    query = next(q for q in load_queries() if q.number == 4)
    with connect(request.getfixturevalue(dsn_fixture)) as conn:
        _, found = run_query(conn, query.variants[0][1])
    assert {row[0] for row in found} == skipped


# ---- the documents as a whole -----------------------------------------------------------------
DOCS = [README["en"], README["pt"], DESIGN_NOTES]


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.name)
def test_relative_links_point_at_something(path: Path) -> None:
    text = without_code(path.read_text(encoding="utf-8"))
    for target in re.findall(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)", text):
        if re.match(r"[a-z]+:", target):
            continue                                            # https://..., mailto:...
        file_part, _, anchor = target.partition("#")
        destination = path.parent / file_part if file_part else path
        assert destination.exists(), f"{path.name}: the link {target} points at nothing"
        if anchor and destination.suffix == ".md":
            assert anchor in anchors(destination.read_text(encoding="utf-8")), \
                f"{path.name}: {destination.name} has no heading for #{anchor}"


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.name)
def test_files_and_tests_named_in_the_docs_exist(path: Path) -> None:
    text = without_code(path.read_text(encoding="utf-8"))
    for name in set(re.findall(r"`([\w.\-]+(?:/[\w.\-]+)+\.(?:py|sql|md|json|yml|toml))`", text)):
        assert (ROOT / name).exists(), f"{path.name} mentions {name}, which does not exist"
    sources = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "tests").glob("test_*.py"))
    for name in set(re.findall(r"`(test_\w+)`", text)):
        assert f"def {name}(" in sources, f"{path.name} mentions the test {name}, which does not exist"


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.name)
def test_no_placeholder_is_left_in_the_docs(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for leftover in ("{{", "}}", "TODO", "FIXME", "em construcao", "under construction"):
        assert leftover not in text, f"{path.name} still contains {leftover!r}"


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.name)
def test_the_constraint_names_in_the_docs_exist(path: Path, catalog: Catalog) -> None:
    named: set[str] = set()
    for header, rows in tables(path.read_text(encoding="utf-8")):
        if header[-1] in ("Name", "Nome"):
            for row in rows:
                named |= set(re.findall(r"`(\w+)`", row[-1]))
    if path == DESIGN_NOTES or path.name.startswith("README"):
        assert named, f"{path.name} should have a table of constraint names"
    for name in named:
        assert name in catalog.constraint_names or name in catalog.trigger_source, f"{name} is not a constraint of the schema"


def test_the_traps_are_as_many_as_the_readmes_say() -> None:
    notes = DESIGN_NOTES.read_text(encoding="utf-8")
    traps = section(notes, "Traps I fell into")
    assert len(re.findall(r"^\d+\. ", traps, re.MULTILINE)) == 10
    assert "ten traps" in read("en") and "dez armadilhas" in read("pt")
