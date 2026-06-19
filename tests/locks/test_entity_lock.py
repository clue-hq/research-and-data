"""M2.4 (ENG-118) — distributed entity locks against a live Redis (skips without one).

Covers every §M2.4 acceptance criterion for the lock: mutual exclusion, TTL auto-expiry vs renewal,
owner-safe release, deadlock-free multi-lock, the context-manager ergonomics, and metric emission.
"""

from __future__ import annotations

import asyncio

import pytest

from clue_research.core import EntityType, new_entity_id
from clue_research.locks import (
    METRIC_LOCK_ACQUIRED,
    METRIC_LOCK_CONTENDED,
    EntityLock,
    entity_lock,
    lock_key,
    multi_lock,
)
from clue_research.obs import InMemorySink, set_metric_sink

from .conftest import redis_conn, run_async

pytestmark = pytest.mark.usefixtures("require_redis")


def test_acquire_is_mutually_exclusive() -> None:
    """Two acquirers of a free lock: exactly one wins; the loser succeeds only after a release."""

    async def _run() -> None:
        async with redis_conn() as redis:
            eid = new_entity_id()
            a = entity_lock(redis, EntityType.ACCOUNT, eid)
            b = entity_lock(redis, EntityType.ACCOUNT, eid)
            assert await a.acquire() is True
            assert await b.acquire() is False  # busy
            assert await a.release() is True
            assert await b.acquire() is True
            await b.release()

    run_async(_run())


def test_acquire_is_mutually_exclusive_under_concurrency() -> None:
    """Under N truly-concurrent acquirers of one free lock, exactly one wins (atomic SET NX)."""

    async def _run() -> None:
        async with redis_conn() as redis:
            eid = new_entity_id()
            locks = [entity_lock(redis, EntityType.ACCOUNT, eid) for _ in range(12)]
            results = await asyncio.gather(*(lk.acquire() for lk in locks))
            assert results.count(True) == 1  # never two holders at once
            for lk in locks:
                if lk.held:
                    await lk.release()

    run_async(_run())


def test_lock_auto_expires_at_ttl() -> None:
    """A holder that dies without releasing has its lock auto-expire (no permanent deadlock)."""

    async def _run() -> None:
        async with redis_conn() as redis:
            eid = new_entity_id()
            dead = entity_lock(redis, EntityType.ACCOUNT, eid, ttl_ms=150)
            assert await dead.acquire() is True  # never released (simulating a crash)
            await asyncio.sleep(0.3)
            fresh = entity_lock(redis, EntityType.ACCOUNT, eid)
            assert await fresh.acquire() is True  # the TTL freed it
            await fresh.release()

    run_async(_run())


def test_long_runner_renews_and_is_not_preempted() -> None:
    """A live long-runner renews its lease and is NOT preempted mid-work."""

    async def _run() -> None:
        async with redis_conn() as redis:
            eid = new_entity_id()
            worker = entity_lock(redis, EntityType.ACCOUNT, eid, ttl_ms=200)
            assert await worker.acquire() is True
            await asyncio.sleep(0.12)
            assert await worker.renew() is True  # extend before expiry
            await asyncio.sleep(0.12)  # total 0.24s > original 0.2s TTL, but renewed
            other = entity_lock(redis, EntityType.ACCOUNT, eid)
            assert await other.acquire() is False  # still held by the renewing worker
            await worker.release()

    run_async(_run())


def test_release_is_owner_safe() -> None:
    """Worker B cannot release worker A's lock (fencing-token check)."""

    async def _run() -> None:
        async with redis_conn() as redis:
            eid = new_entity_id()
            key = lock_key(EntityType.ACCOUNT, eid)
            a = EntityLock(redis, key, token="owner-a")
            b = EntityLock(redis, key, token="impostor-b")
            assert await a.acquire() is True
            assert await b.release() is False  # B is not the owner → no-op
            # A still holds it: a third acquirer fails until A releases.
            assert await entity_lock(redis, EntityType.ACCOUNT, eid).acquire() is False
            assert await a.release() is True

    run_async(_run())


def test_multi_lock_is_deadlock_free_under_cross_contention() -> None:
    """Two merges contending on the same pair in opposite request orders never deadlock (both
    acquire in the same sorted key order)."""

    async def _run() -> None:
        async with redis_conn() as redis:
            a, b = new_entity_id(), new_entity_id()
            done: list[str] = []

            async def merge(label: str, order: list[tuple[EntityType, object]]) -> None:
                async with multi_lock(redis, order, ttl_ms=2000):  # type: ignore[arg-type]
                    await asyncio.sleep(0.05)  # hold both, simulating the merge write
                done.append(label)

            await asyncio.wait_for(
                asyncio.gather(
                    merge("x", [(EntityType.ACCOUNT, a), (EntityType.ACCOUNT, b)]),
                    merge("y", [(EntityType.ACCOUNT, b), (EntityType.ACCOUNT, a)]),
                ),
                timeout=5.0,  # a deadlock would hang past this
            )
            assert set(done) == {"x", "y"}

    run_async(_run())


def test_context_manager_acquires_and_releases() -> None:
    """`async with entity_lock(...)` holds inside the block and frees on exit."""

    async def _run() -> None:
        async with redis_conn() as redis:
            eid = new_entity_id()
            async with entity_lock(redis, EntityType.ACCOUNT, eid):
                assert await entity_lock(redis, EntityType.ACCOUNT, eid).acquire() is False
            # released on exit
            after = entity_lock(redis, EntityType.ACCOUNT, eid)
            assert await after.acquire() is True
            await after.release()

    run_async(_run())


def test_lock_metrics_are_emitted() -> None:
    """Acquire / contention counters are emitted through the obs metric sink."""

    async def _run() -> None:
        sink = InMemorySink()
        set_metric_sink(sink)
        try:
            async with redis_conn() as redis:
                eid = new_entity_id()
                a = entity_lock(redis, EntityType.ACCOUNT, eid)
                b = entity_lock(redis, EntityType.ACCOUNT, eid)
                await a.acquire()
                await b.acquire()  # contended
                assert sink.counter(METRIC_LOCK_ACQUIRED, entity_type="account") >= 1.0
                assert sink.counter(METRIC_LOCK_CONTENDED, entity_type="account") >= 1.0
                await a.release()
        finally:
            set_metric_sink(InMemorySink())

    run_async(_run())
