"""DB-test fixtures and the reachable-DB gate (M0.3 / ENG-114).

Every DB-requiring test ``pytest.skip``s gracefully when ``CLUE_DATABASE_URL`` is unset OR the
database is unreachable, so the default ``make check`` stays green without a database (§M0.3). When
the DSN is set and the DB is up, the tests run.

These tests do not depend on ``pytest-asyncio``: the async engine work is driven from synchronous
test bodies via :func:`run_async` (a thin ``asyncio.run`` wrapper), keeping the M0.1 dev toolchain
unchanged.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Coroutine
from typing import Any

import pytest
from sqlalchemy import text

from clue_research.db import DATABASE_URL_ENV, create_engine


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine to completion from a synchronous test body."""
    return asyncio.run(coro)


async def _probe_db() -> bool:
    """Return True iff a connection opens and ``SELECT 1`` succeeds against the configured DSN."""
    engine = create_engine()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


def _db_available() -> bool:
    """The reachable-DB gate: DSN env var set AND a trivial query succeeds."""
    if not os.environ.get(DATABASE_URL_ENV):
        return False
    try:
        return run_async(_probe_db())
    except Exception:
        return False


@pytest.fixture(scope="session")
def db_available() -> bool:
    return _db_available()


@pytest.fixture
def require_db(db_available: bool) -> None:
    """Skip the test unless ``CLUE_DATABASE_URL`` is set and the database is reachable."""
    if not db_available:
        pytest.skip(
            f"{DATABASE_URL_ENV} unset or database unreachable; "
            "set it and run `make db-up` to exercise the DB tests"
        )
