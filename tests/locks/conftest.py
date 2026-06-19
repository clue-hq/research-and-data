"""Lock test harness (M2.4) — a reachable-Redis gate (skips gracefully without one).

These tests exercise real Redis semantics (atomic ``SET NX PX``, owner-safe Lua release/renew, TTL
auto-expiry, concurrent contention), so they need a reachable Redis. Like the DB tests, they
``pytest.skip`` when ``CLUE_REDIS_URL`` is unset or Redis is unreachable, so the default ``make
check`` stays green without Redis; with ``make redis-up`` + the DSN set, they run. We reuse the M0.3
``run_async`` single-loop runner (DRY). Tests use fresh entity ids per case, so they never collide
even on a shared Redis (no flush needed).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from redis.asyncio import Redis

from clue_research.locks import REDIS_URL_ENV, create_redis
from tests.db.conftest import run_async as run_async


async def _probe_redis() -> bool:
    client = create_redis()
    try:
        await client.ping()
        return True
    except Exception:
        return False
    finally:
        await client.aclose()


def _redis_available() -> bool:
    """The reachable-Redis gate: DSN env var set AND a ``PING`` succeeds."""
    if not os.environ.get(REDIS_URL_ENV):
        return False
    try:
        return run_async(_probe_redis())
    except Exception:
        return False


@pytest.fixture(scope="session")
def redis_available() -> bool:
    return _redis_available()


@pytest.fixture
def require_redis(redis_available: bool) -> None:
    if not redis_available:
        pytest.skip(
            f"{REDIS_URL_ENV} unset or Redis unreachable; set it and run `make redis-up` "
            "to exercise the lock tests"
        )


@asynccontextmanager
async def redis_conn() -> AsyncIterator[Redis]:
    """Yield a fresh async Redis client, closed on exit (use inside a ``run_async`` body)."""
    client = create_redis()
    try:
        yield client
    finally:
        await client.aclose()
