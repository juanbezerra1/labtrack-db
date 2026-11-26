"""The files around the code (Docker Compose, the CI workflow, the licence, line endings) say things that the
README and the tool rely on. These tests keep them consistent with each other."""

from __future__ import annotations

import re
from urllib.parse import urlparse

import pytest

from labtrack.db import DEFAULT_DSN, project_root

ROOT = project_root()


def text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_the_compose_file_is_the_database_the_tool_connects_to_by_default() -> None:
    compose = text("docker-compose.yml")
    default = urlparse(DEFAULT_DSN)
    environment = dict(re.findall(r"^\s+(POSTGRES_\w+): (\S+)$", compose, re.MULTILINE))
    assert environment == {
        "POSTGRES_USER": default.username,
        "POSTGRES_PASSWORD": default.password,
        "POSTGRES_DB": default.path.lstrip("/"),
    }
    assert re.search(r"^\s+image: postgres:16$", compose, re.MULTILINE)
    assert f'"${{LABTRACK_PORT:-{default.port}}}:5432"' in compose     # the override the README describes
    assert "pg_isready" in compose                                     # what `docker compose up --wait` waits for


def test_the_readme_describes_the_compose_file() -> None:
    for name in ("README.md", "README.pt-BR.md"):
        readme = text(name)
        assert "docker compose up -d --wait" in readme
        assert "LABTRACK_PORT=5433 docker compose up -d --wait" in readme
        assert DEFAULT_DSN in readme


def test_the_ci_workflow_runs_what_the_readme_says() -> None:
    workflow = text(".github/workflows/ci.yml")
    assert re.search(r"^\s+image: postgres:16$", workflow, re.MULTILINE)
    assert re.search(r'python-version: \["3\.10", "3\.13"\]', workflow)
    assert re.findall(r"^\s+runs-on: (\S+)$", workflow, re.MULTILINE) == ["ubuntu-latest"]
    assert re.search(r"^\s+LABTRACK_TEST_DSN: postgresql://\S+$", workflow, re.MULTILINE)
    steps = re.findall(r"^\s+run: (.+)$", workflow, re.MULTILINE)
    assert steps == ['python -m pip install -e ".[dev]"', "ruff check .", "mypy src tests scripts", "pytest"]


def test_the_oldest_python_in_ci_is_the_oldest_the_project_claims() -> None:
    pyproject = text("pyproject.toml")
    assert re.search(r'^requires-python = ">=3\.10"$', pyproject, re.MULTILINE)
    assert re.search(r'^python_version = "3\.10"$', pyproject, re.MULTILINE)     # mypy
    assert re.search(r'^target-version = "py310"$', pyproject, re.MULTILINE)     # ruff


def test_the_dev_extras_are_what_ci_uses() -> None:
    found = re.search(r"^dev = \[(.*)\]$", text("pyproject.toml"), re.MULTILINE)
    assert found
    names = {re.split(r"[<>=!~\[ ]", item.strip().strip('"'))[0] for item in found.group(1).split(",")}
    assert names == {"pytest", "ruff", "mypy"}


def test_the_licence_is_mit_and_names_the_author() -> None:
    licence = text("LICENSE")
    assert licence.startswith("MIT License")
    assert re.search(r"^Copyright \(c\) 20\d\d Juan Bezerra$", licence, re.MULTILINE)
    assert re.search(r'^license = \{ text = "MIT" \}$', text("pyproject.toml"), re.MULTILINE)


@pytest.mark.parametrize("pattern", ["*.csv", "*.sql", "*.json", "*.md", "*.py", "SHA256SUMS"])
def test_git_is_told_to_keep_line_feeds_where_checksums_are_computed(pattern: str) -> None:
    rules = [line.split() for line in text(".gitattributes").splitlines() if line and not line.startswith("#")]
    assert [pattern, "text", "eol=lf"] in rules


def test_no_text_file_of_the_repository_has_windows_line_endings() -> None:
    suffixes = {".csv", ".sql", ".json", ".md", ".py", ".yml", ".toml"}
    skipped = {".git", ".venv", "venv", "env", "build", "dist", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
    offenders = [
        str(path.relative_to(ROOT))
        for path in ROOT.rglob("*")
        if path.is_file()
        and not skipped.intersection(path.relative_to(ROOT).parts)
        and (path.suffix in suffixes or path.name in {"SHA256SUMS", "LICENSE"})
        and b"\r\n" in path.read_bytes()
    ]
    assert offenders == []
