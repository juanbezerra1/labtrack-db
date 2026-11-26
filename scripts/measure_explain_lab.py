"""Measure the EXPLAIN lab: run every lesson several times and keep the median time of each step.

    python scripts/measure_explain_lab.py --dsn postgresql://... --runs 5 --out docs/measurements/explain-lab-large.json

Why this exists: a timing in the README should come from somewhere you can check. The first run of every
lesson is a warm-up and is thrown away (a cold cache can be many times slower), then the lesson runs --runs
more times and the median is kept. The numbers are the "Execution Time" that EXPLAIN (ANALYZE) reports, in
milliseconds. They depend on the machine, so the file records the machine and the server settings too.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
from datetime import date
from pathlib import Path
from typing import Any

from labtrack.db import connect, scalar
from labtrack.explain import check_expectations, load_lessons, run_lesson, scale_of

SETTINGS = ("shared_buffers", "work_mem", "effective_cache_size", "max_parallel_workers_per_gather", "jit",
            "random_page_cost")


def installed_memory_gib() -> float | None:
    """RAM from /proc/meminfo (Linux); None where that file does not exist."""
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return round(int(line.split()[1]) / 1024 / 1024, 1)
    except OSError:
        pass
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dsn", help="connection string (default: $LABTRACK_DSN or the docker-compose database)")
    ap.add_argument("--runs", type=int, default=5, help="measured runs per lesson, after one warm-up run (default 5)")
    ap.add_argument("--out", type=Path, help="write the results to this JSON file")
    args = ap.parse_args(argv)

    with connect(args.dsn) as conn:
        scale = scale_of(conn)
        rows = int(scalar(conn, "SELECT count(*) FROM lab.trial_feature"))
        version = str(scalar(conn, "SELECT version()"))
        settings = {name: str(scalar(conn, "SELECT current_setting(%s)", (name,))) for name in SETTINGS}
        lessons_out: dict[str, Any] = {}
        for lesson in load_lessons():
            samples: dict[str, list[float]] = {}
            for attempt in range(args.runs + 1):
                result = run_lesson(conn, lesson)
                problems = check_expectations(result)
                if problems:
                    print(f"lesson {lesson.number}: the plans are not as the lesson says on this database "
                          f"(scale {scale}): {problems[0]}", file=sys.stderr)
                    return 1
                if attempt == 0:
                    continue
                for label, plan in result.explains.items():
                    samples.setdefault(label, []).append(plan.execution_ms)
            steps = {
                label: {"median_ms": round(statistics.median(v), 1), "min_ms": round(min(v), 1),
                        "max_ms": round(max(v), 1)}
                for label, v in samples.items()
            }
            lessons_out[str(lesson.number)] = {"title": lesson.title, "steps": steps}
            print(f"lesson {lesson.number}: " + ", ".join(f"{k} {v['median_ms']} ms" for k, v in steps.items()))

    report = {
        "measured_on": date.today().isoformat(),
        "scale": scale,
        "trial_feature_rows": rows,
        "runs_per_lesson": args.runs,
        "machine": {"os": platform.platform(), "cpus": os.cpu_count(), "memory_gib": installed_memory_gib()},
        "server": {"version": version, "settings": settings},
        "lessons": lessons_out,
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
