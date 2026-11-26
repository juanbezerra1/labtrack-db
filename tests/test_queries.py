"""The teaching queries: they run, all variants of one file agree, and the result matches the golden copy."""

from __future__ import annotations

import pytest

from labtrack.db import connect
from labtrack.queries import Query, format_table, load_queries, run_query

from .golden import check_golden

QUERIES = load_queries()


def test_the_queries_are_numbered_without_gaps() -> None:
    assert [q.number for q in QUERIES] == list(range(1, len(QUERIES) + 1))
    assert all(q.path.name.startswith(f"{q.number:02d}_") for q in QUERIES)


@pytest.mark.parametrize("query", QUERIES, ids=[q.stem for q in QUERIES])
def test_query_result_matches_golden_and_variants_agree(
        request: pytest.FixtureRequest, small_dsn: str, query: Query) -> None:
    results = []
    with connect(small_dsn) as conn:
        for name, sql in query.variants:
            columns, rows = run_query(conn, sql)
            results.append((name, columns, rows))
    first_name, first_columns, first_rows = results[0]
    for name, columns, rows in results[1:]:
        assert columns == first_columns, f"{query.stem}: variant {name} has other columns than {first_name}"
        assert rows == first_rows, f"{query.stem}: variant {name} returns other rows than {first_name}"
    assert first_rows, f"{query.stem} returns nothing: a lesson that shows nothing teaches nothing"
    check_golden(request, f"query_{query.stem}", {"columns": first_columns, "rows": [list(r) for r in first_rows]})


@pytest.mark.parametrize("query", QUERIES, ids=[q.stem for q in QUERIES])
def test_every_query_explains_itself(query: Query) -> None:
    header = query.path.read_text(encoding="utf-8").split("\n\n", 1)[0]
    for word in ("Question", "Concepts"):
        assert f"-- {word}" in header, f"{query.stem}: the header comment needs a '{word}' line"


def test_format_table_aligns_numbers_to_the_right() -> None:
    text = format_table(["name", "n"], [("a", 5), ("bcd", 120)])
    assert text.splitlines()[0] == "name |   n"
    assert text.splitlines()[2] == "a    |   5"
    assert text.splitlines()[-1] == "(2 rows)"
