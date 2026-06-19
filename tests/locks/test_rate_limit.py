"""M2.4 (ENG-118) — the distributed token-bucket rate limiter against a live Redis."""

from __future__ import annotations

import asyncio

import pytest

from clue_research.core import new_run_id
from clue_research.locks import RateLimiter

from .conftest import redis_conn, run_async

pytestmark = pytest.mark.usefixtures("require_redis")


def test_burst_capped_at_capacity() -> None:
    """With no refill (rate 0), exactly ``capacity`` calls are allowed, the rest denied."""

    async def _run() -> None:
        async with redis_conn() as redis:
            limiter = RateLimiter(redis, rate_per_sec=0.0, capacity=5)
            source = f"provider:{new_run_id()}"
            allowed = [await limiter.acquire(source) for _ in range(8)]
            assert allowed.count(True) == 5
            assert allowed.count(False) == 3

    run_async(_run())


def test_separate_source_keys_are_independent() -> None:
    """Each ``source_key`` gets its own bucket — one exhausted source does not starve another."""

    async def _run() -> None:
        async with redis_conn() as redis:
            limiter = RateLimiter(redis, rate_per_sec=0.0, capacity=2)
            s1, s2 = f"a:{new_run_id()}", f"b:{new_run_id()}"
            assert [await limiter.acquire(s1) for _ in range(3)].count(True) == 2
            assert [await limiter.acquire(s2) for _ in range(3)].count(True) == 2

    run_async(_run())


def test_bucket_refills_over_time() -> None:
    """An empty bucket refills at ``rate_per_sec`` and allows again after enough time."""

    async def _run() -> None:
        async with redis_conn() as redis:
            # rate=2/s, capacity=1: refilling one token takes ~0.5s, a wide margin over the
            # sub-ms call overhead — so the "immediately empty" assertion is not timing-flaky.
            limiter = RateLimiter(redis, rate_per_sec=2.0, capacity=1)
            source = f"refill:{new_run_id()}"
            assert await limiter.acquire(source) is True  # consumes the one token
            assert await limiter.acquire(source) is False  # empty (needs ~0.5s to refill one)
            await asyncio.sleep(1.0)  # 2/s * 1.0s = 2 tokens refilled (capped at capacity=1)
            assert await limiter.acquire(source) is True

    run_async(_run())


def test_concurrent_workers_respect_budget() -> None:
    """N concurrent workers on one source collectively consume at most ``capacity`` (atomic Lua)."""

    async def _run() -> None:
        async with redis_conn() as redis:
            limiter = RateLimiter(redis, rate_per_sec=0.0, capacity=5)
            source = f"concurrent:{new_run_id()}"
            results = await asyncio.gather(*(limiter.acquire(source) for _ in range(20)))
            assert results.count(True) == 5  # never oversubscribed despite 20 concurrent callers

    run_async(_run())
