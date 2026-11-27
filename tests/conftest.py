"""Test fixtures.

The tests need a real PostgreSQL server and a user that may create databases. Point them at one with

    LABTRACK_TEST_DSN=postgresql://user:password@localhost:5432/postgres

Every test database is created from scratch with a random name and dropped at the end, so nothing
you have in the server is touched.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator

import psycopg
import pytest

from labtrack.db import connect, with_dbname
from labtrack.migrate import migrate
from labtrack.seed import seed

ADMIN_DSN = os.environ.get("LABTRACK_TEST_DSN", "")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-golden", action="store_true", help="rewrite tests/golden/*.json from the current results"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if ADMIN_DSN:
        return
    skip = pytest.mark.skip(reason="set LABTRACK_TEST_DSN to a PostgreSQL server where databases may be created")
    for item in items:
        item.add_marker(skip)


@pytest.fixture(scope="session")
def make_db() -> Iterator[Callable[[], str]]:
    """A factory of empty databases; returns the DSN of each. All are dropped when the session ends."""
    created: list[str] = []

    def factory() -> str:
        name = f"labtrack_t_{uuid.uuid4().hex[:10]}"
        with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
            admin.execute(f'CREATE DATABASE "{name}"')
        created.append(name)
        return with_dbname(ADMIN_DSN, name)

    yield factory
    with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
        for name in created:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(scope="session")
def migrated_dsn(make_db: Callable[[], str]) -> str:
    """One database at the latest migration, with no data."""
    dsn = make_db()
    with connect(dsn) as conn:
        migrate(conn, log=lambda _: None)
    return dsn


@pytest.fixture
def conn(migrated_dsn: str) -> Iterator[psycopg.Connection]:
    """A connection inside a transaction that is rolled back at the end: tests never see each other's rows."""
    with connect(migrated_dsn) as connection:
        connection.execute("SET TIME ZONE 'UTC'")
        with connection.transaction(force_rollback=True):
            yield connection


def _seeded(make_db: Callable[[], str], scale: str) -> str:
    dsn = make_db()
    with connect(dsn) as conn:
        migrate(conn, log=lambda _: None)
        seed(conn, scale=scale, log=lambda _: None)
    return dsn


@pytest.fixture(scope="session")
def tiny_dsn(make_db: Callable[[], str]) -> str:
    return _seeded(make_db, "tiny")


@pytest.fixture(scope="session")
def small_dsn(make_db: Callable[[], str]) -> str:
    return _seeded(make_db, "small")


@pytest.fixture(scope="session")
def medium_dsn(make_db: Callable[[], str]) -> str:
    return _seeded(make_db, "medium")
