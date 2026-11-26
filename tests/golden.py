"""Golden files: the expected result of a query or a count, kept in tests/golden/ and compared exactly.

When a result changes on purpose (you edited the seed or a query), run  pytest --update-golden  and read
the diff in git: that diff is the review of what changed.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

GOLDEN = Path(__file__).parent / "golden"


def _plain(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def check_golden(request: pytest.FixtureRequest, name: str, actual: Any) -> None:
    path = GOLDEN / f"{name}.json"
    actual = _plain(actual)
    text = json.dumps(actual, indent=1, ensure_ascii=False) + "\n"
    if request.config.getoption("--update-golden"):
        GOLDEN.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return
    if not path.exists():
        pytest.fail(f"no golden file {path.name}: run pytest --update-golden once, then review it with git")
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert actual == expected, f"result differs from tests/golden/{path.name}; if the change is intended: pytest --update-golden"
