"""Distributed in-flight entity locks over Redis (M2.4).

Substrate §2 prescribes ``lock(account_id)`` before any expensive work so two workers never research
(or merge) the same entity — replacing the prototype's ``run_pause.flag`` / ad-hoc in-flight checks.
This is both a **correctness** guard (no double-write, no merge race) and a **cost** guard (no
duplicate spend — Doc C §3 per-entity budget discipline depends on single-flight execution).

The primitive is the standard single-instance Redis lock done safely:

* **atomic acquire** — ``SET key token NX PX ttl`` (one round-trip, no check-then-set race);
* **owner-safe release / renew** — a Lua compare-and-act so a *slow* worker can never release or
  extend a lock that has since been taken over by another (the fencing-token check);
* **TTL with renewal** — a crashed holder's lock auto-expires at the TTL (no permanent deadlock —
  the failure ``run_pause.flag`` could not handle), while a live long-runner ``renew()``s its lease
  and is not preempted;
* **deadlock-free multi-lock** — :func:`multi_lock` acquires several entity locks in a deterministic
  (sorted-key) order, so two merges contending on the same pair can never circular-wait.

Locks are *advisory coordination*, distinct from M1's append-only / idempotency guarantees: they
prevent *wasted concurrent work*; correctness on retry still rests on idempotency keys (substrate
§5c) and append-only writes (M1). Killing Redis therefore degrades to possible duplicate work, never
to corrupted Postgres truth.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Sequence
from types import TracebackType

from redis.asyncio import Redis

from clue_research.core import EntityId, EntityType
from clue_research.obs import get_metric_sink, traced_step

# Default lease: long enough for a unit of expensive work, short enough that a crashed holder frees
# the entity reasonably fast. Callers tune per workload (a deep-profiling run uses a longer lease).
DEFAULT_TTL_MS = 30_000

# Metric names (the "research.*" convention from obs/metrics.py). Lock contention/expiry is the
# Doc C §6 observability signal that single-flight is working.
METRIC_LOCK_ACQUIRED = "research.lock.acquired"
METRIC_LOCK_CONTENDED = "research.lock.contended"
METRIC_LOCK_RELEASED = "research.lock.released"
METRIC_LOCK_RENEWED = "research.lock.renewed"

# Owner-safe Lua: act only if the stored token still matches this holder's fencing token.
_RELEASE = (
    "if redis.call('get', KEYS[1]) == ARGV[1] "
    "then return redis.call('del', KEYS[1]) else return 0 end"
)
_RENEW = (
    "if redis.call('get', KEYS[1]) == ARGV[1] "
    "then return redis.call('pexpire', KEYS[1], ARGV[2]) else return 0 end"
)


class LockTimeout(TimeoutError):
    """Raised when a blocking acquire (or an ``async with`` entry) cannot get the lock in time."""


def lock_key(entity_type: EntityType, entity_id: EntityId, *, tenant: str | None = None) -> str:
    """The lock keyspace: ``lock:{type}:{id}``, tenant-namespaced where reuse boundaries require it
    (coordinated with M2.5 — public-entity work may be cross-tenant single-flight; client-private
    work is tenant-scoped)."""
    base = f"lock:{entity_type.value}:{entity_id}"
    return f"lock:{tenant}:{entity_type.value}:{entity_id}" if tenant else base


class EntityLock:
    """An advisory, owner-fenced, TTL'd lock on one entity. Use via :func:`entity_lock`."""

    def __init__(
        self,
        redis: Redis,
        key: str,
        *,
        ttl_ms: int = DEFAULT_TTL_MS,
        token: str | None = None,
        attributes: dict[str, str] | None = None,
    ) -> None:
        self._redis = redis
        self._key = key
        self._ttl_ms = ttl_ms
        self._token = token or uuid.uuid4().hex  # the fencing token (this holder's identity)
        self._attrs = attributes or {}
        self._held = False
        self._heartbeat: asyncio.Task[None] | None = None

    @property
    def held(self) -> bool:
        return self._held

    @property
    def token(self) -> str:
        return self._token

    async def acquire(
        self, *, blocking: bool = False, timeout: float | None = None, poll_interval: float = 0.05
    ) -> bool:
        """Try to acquire the lock. Non-blocking by default (returns ``True``/``False`` at once).

        With ``blocking=True`` it polls until acquired or ``timeout`` seconds elapse (``None`` =
        wait indefinitely). Exactly one of two concurrent acquirers of a free lock wins.
        """
        with traced_step("identity.lock.acquire", **self._attrs):
            loop = asyncio.get_running_loop()
            deadline = None if timeout is None else loop.time() + timeout
            while True:
                acquired = await self._redis.set(self._key, self._token, nx=True, px=self._ttl_ms)
                if acquired:
                    self._held = True
                    get_metric_sink().add(METRIC_LOCK_ACQUIRED, 1, self._attrs)
                    return True
                get_metric_sink().add(METRIC_LOCK_CONTENDED, 1, self._attrs)
                if not blocking:
                    return False
                if deadline is None:
                    await asyncio.sleep(poll_interval)
                    continue
                # Sleep only up to the deadline, so the final attempt lands *at* it (not one poll
                # short) — then give up if we've run out of time.
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return False
                await asyncio.sleep(min(poll_interval, remaining))

    async def release(self) -> bool:
        """Release the lock **iff** we still own it (owner-safe). ``True`` if we deleted it."""
        result = await self._redis.eval(_RELEASE, 1, self._key, self._token)
        self._held = False
        released = bool(result)
        if released:
            get_metric_sink().add(METRIC_LOCK_RELEASED, 1, self._attrs)
        return released

    async def renew(self, *, ttl_ms: int | None = None) -> bool:
        """Extend the lease **iff** we still own it (heartbeat). Returns ``True`` if extended."""
        result = await self._redis.eval(_RENEW, 1, self._key, self._token, ttl_ms or self._ttl_ms)
        renewed = bool(result)
        if renewed:
            get_metric_sink().add(METRIC_LOCK_RENEWED, 1, self._attrs)
        return renewed

    async def _run_heartbeat(self) -> None:
        """Renew the lease at ⅓-TTL cadence while held, so a holder outrunning its TTL is never
        preempted. Stops as soon as a renewal fails (the lease was lost / taken over)."""
        interval = max(0.01, self._ttl_ms / 1000.0 / 3.0)
        while True:
            await asyncio.sleep(interval)
            if not await self.renew():
                break

    async def __aenter__(self) -> EntityLock:
        if not await self.acquire(blocking=True, timeout=self._ttl_ms / 1000.0):
            raise LockTimeout(f"could not acquire {self._key} within its lease window")
        # Auto-renew for the duration of the held block (manual acquire() keeps the no-heartbeat
        # contract — the caller renews). So `async with` long work is never silently preempted.
        self._heartbeat = asyncio.create_task(self._run_heartbeat())
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._heartbeat is not None:
            self._heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat
            self._heartbeat = None
        await self.release()


def entity_lock(
    redis: Redis,
    entity_type: EntityType,
    entity_id: EntityId,
    *,
    ttl_ms: int = DEFAULT_TTL_MS,
    tenant: str | None = None,
    token: str | None = None,
) -> EntityLock:
    """Build an :class:`EntityLock` for ``(entity_type, entity_id)`` (the common factory)."""
    return EntityLock(
        redis,
        lock_key(entity_type, entity_id, tenant=tenant),
        ttl_ms=ttl_ms,
        token=token,
        attributes={"entity_type": entity_type.value},
    )


class MultiLock:
    """Acquire several entity locks in a deterministic (sorted-key) order — deadlock-free. Use via
    :func:`multi_lock`. On ``__aexit__`` all held locks are released in reverse order."""

    def __init__(self, locks: Sequence[EntityLock]) -> None:
        # Sort by key so any two MultiLocks over the same set acquire in the same order (no
        # circular wait — the classic two-merge cross-contention deadlock cannot form).
        self._locks = sorted(locks, key=lambda lock: lock._key)

    async def __aenter__(self) -> list[EntityLock]:
        acquired: list[EntityLock] = []
        try:
            for lock in self._locks:
                if not await lock.acquire(blocking=True, timeout=lock._ttl_ms / 1000.0):
                    raise LockTimeout(f"could not acquire {lock._key} for a multi-lock")
                acquired.append(lock)
        except BaseException:
            for lock in reversed(acquired):
                await lock.release()
            raise
        return acquired

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        for lock in reversed(self._locks):
            if lock.held:
                await lock.release()


def multi_lock(
    redis: Redis,
    targets: Sequence[tuple[EntityType, EntityId]],
    *,
    ttl_ms: int = DEFAULT_TTL_MS,
    tenant: str | None = None,
) -> MultiLock:
    """Build a :class:`MultiLock` over several ``(entity_type, entity_id)`` targets (e.g. the two
    candidates a merge locks). Acquisition order is deterministic, so it never deadlocks."""
    return MultiLock(
        [entity_lock(redis, et, eid, ttl_ms=ttl_ms, tenant=tenant) for et, eid in targets]
    )
