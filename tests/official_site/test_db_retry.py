"""Repository retry policy is narrow, bounded, and free of provider-side effects."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.exc import DBAPIError

from clue_research.official_site.db_retry import (
    database_sqlstate,
    retry_deadlocked_transaction,
)


class _DriverFailure(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


def _db_failure(sqlstate: str) -> DBAPIError:
    return DBAPIError("redacted", {}, _DriverFailure(sqlstate), False)


def test_deadlock_retry_is_bounded_to_transaction_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    sleeps: list[float] = []

    async def _sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _sleep)
    monkeypatch.setattr("random.uniform", lambda _low, _high: 1.0)

    @retry_deadlocked_transaction(stage="fixture", max_retries=3)
    async def operation() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise _db_failure("40P01")
        return "committed"

    assert asyncio.run(operation()) == "committed"
    assert calls == 3
    assert sleeps == [0.01, 0.02]


def test_non_deadlock_database_failure_is_never_retried() -> None:
    calls = 0

    @retry_deadlocked_transaction(stage="fixture", max_retries=3)
    async def operation() -> None:
        nonlocal calls
        calls += 1
        raise _db_failure("40001")

    with pytest.raises(DBAPIError):
        asyncio.run(operation())
    assert calls == 1


def test_deadlock_retry_exhaustion_reraises_after_bounded_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def _sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _sleep)

    @retry_deadlocked_transaction(stage="fixture", max_retries=2)
    async def operation() -> None:
        nonlocal calls
        calls += 1
        raise _db_failure("40P01")

    with pytest.raises(DBAPIError):
        asyncio.run(operation())
    assert calls == 3


def test_sqlstate_reader_handles_sqlalchemy_driver_nesting() -> None:
    assert database_sqlstate(_db_failure("40P01")) == "40P01"
    assert database_sqlstate(RuntimeError("not a database error")) is None
