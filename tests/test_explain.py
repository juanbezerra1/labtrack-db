"""The EXPLAIN lab: every lesson's plans are as the lesson claims, and running a lesson changes nothing.

These tests need the medium scale (about a million feature values), where the planner makes the choices the
lessons describe. They check plan SHAPES and row counts, never timings, which depend on the machine.
"""

from __future__ import annotations

import pytest

from labtrack.db import connect, scalar
from labtrack.explain import (
    ExplainResult,
    Lesson,
    LessonResult,
    check_expectations,
    load_lessons,
    render,
    run_lesson,
    scale_of,
)

LESSONS = load_lessons()


@pytest.fixture(scope="module")
def results(medium_dsn: str) -> dict[int, LessonResult]:
    with connect(medium_dsn) as conn:
        return {lesson.number: run_lesson(conn, lesson, with_text=True) for lesson in LESSONS}


def test_the_lessons_are_numbered_without_gaps() -> None:
    assert [lesson.number for lesson in LESSONS] == list(range(1, len(LESSONS) + 1))
    assert all(lesson.path.name.startswith(f"{lesson.number:02d}_") for lesson in LESSONS)
    assert all(lesson.expectations for lesson in LESSONS), "a lesson without expectations proves nothing"


def test_the_medium_scale_is_recognised(medium_dsn: str, small_dsn: str) -> None:
    with connect(medium_dsn) as conn:
        assert scale_of(conn) == "medium"
    with connect(small_dsn) as conn:
        assert scale_of(conn) == "small"


@pytest.mark.parametrize("lesson", LESSONS, ids=[lesson.stem for lesson in LESSONS])
def test_the_plans_are_as_the_lesson_says(results: dict[int, LessonResult], lesson: Lesson) -> None:
    assert check_expectations(results[lesson.number]) == []


@pytest.mark.parametrize("lesson", LESSONS, ids=[lesson.stem for lesson in LESSONS])
def test_every_lesson_renders(results: dict[int, LessonResult], lesson: Lesson) -> None:
    text = render(results[lesson.number], plans=True)
    assert f"Lesson {lesson.number}: {lesson.title}" in text and "as the lesson says" in text


def buffers(plan: ExplainResult) -> int:
    return int(plan.root["shared_hit"] + plan.root["shared_read"])


def test_lesson_01_the_index_reads_far_fewer_pages(results: dict[int, LessonResult]) -> None:
    r = results[1].explains
    assert buffers(r["after"]) * 10 < buffers(r["before"])
    assert r["after"].root["actual_rows"] == r["before"].root["actual_rows"] > 0   # same answer, different road


def test_lesson_03_an_index_only_scan_never_visits_the_table(results: dict[int, LessonResult]) -> None:
    only = results[3].explains["after"].first("Index Only Scan")
    assert only["heap_fetches"] == 0
    assert results[3].explains["before"].root["actual_rows"] == only["actual_rows"] > 0


def test_lesson_04_the_partial_index_is_much_smaller(results: dict[int, LessonResult]) -> None:
    (columns, rows), = [results[4].shows[k] for k in results[4].shows]
    sizes = {r[0]: r[1] for r in rows}
    unit_kb = {"bytes": 1 / 1024, "kB": 1, "MB": 1024}

    def kb(text: str) -> float:
        number, unit = text.split()
        return float(number) * unit_kb[unit]

    assert kb(sizes["partial (WHERE NOT valid)"]) * 3 < kb(sizes["full"])


def test_lesson_05_the_same_join_changes_algorithm(results: dict[int, LessonResult]) -> None:
    few, many = results[5].explains["few rows"], results[5].explains["many rows"]
    assert few.first("Nested Loop")["actual_rows"] < 1000
    assert many.first("Hash Join")["actual_rows"] > 100_000


def test_lesson_06_work_mem_changes_the_sort_method(results: dict[int, LessonResult]) -> None:
    r = results[6].explains
    assert "external merge" in r["default memory"].first("Sort")["description"]
    assert "quicksort" in r["more memory"].first("Sort")["description"]
    assert r["more memory"].first("Sort")["sort_space_kb"] > 4 * 1024            # it would not have fitted in the default 4 MB
    assert r["only the top ten"].first("Sort")["sort_space_kb"] < 1024        # a heap of ten rows: kilobytes


def ratio(plan: ExplainResult) -> float:
    node = plan.first("Seq Scan on recording")
    est, act = max(node["estimated_rows"], 1), max(node["actual_rows"], 1)
    return float(max(est / act, act / est))


def test_lesson_07_extended_statistics_fix_the_estimate(results: dict[int, LessonResult]) -> None:
    r = results[7].explains
    assert ratio(r["independent columns"]) > 3
    assert ratio(r["with extended statistics"]) < 1.5


def test_lesson_08_offset_reads_the_skipped_rows_and_keyset_does_not(results: dict[int, LessonResult]) -> None:
    r = results[8].explains
    assert r["offset"].first("Index Scan")["actual_rows"] >= 29_980
    assert r["keyset"].first("Index Scan")["actual_rows"] <= 25
    assert buffers(r["keyset"]) * 10 < buffers(r["offset"])


def test_running_the_lessons_changed_nothing(medium_dsn: str, results: dict[int, LessonResult]) -> None:  # noqa: ARG001
    """The lab runs in a transaction it rolls back: no stray index, statistics object or setting is left."""
    with connect(medium_dsn) as conn:
        names = {r[0] for r in conn.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'lab'")}
        assert not {n for n in names if n.startswith(("trial_feature_feature_value", "trial_feature_covering", "trial_rejected", "trial_reason_full"))}
        assert scalar(conn, "SELECT count(*) FROM pg_statistic_ext WHERE stxname = 'recording_modality_channels'") == 0
