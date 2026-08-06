"""The per-entity single-flight lock factory for the ``api`` composition root (Doc C §4).

A tiny dependency-free module (imports only ``core`` / ``locks`` / ``durable`` — never ``clue_api``)
so **both** the deep composition (:mod:`clue_api.deep.composition`) and the fleet wiring
(:mod:`clue_api.fleet_wiring`) can import the lock seam without an import cycle. It holds two shapes
of the Doc C §4 account-entity single-flight lock:

* :func:`build_account_lock_factory` (re-exported from :mod:`clue_api.fleet_wiring`) — the eager
  factory: resolves the Redis client at construction. Requires an active ``redis_lifespan``.
* :func:`lazy_account_lock_factory` — the **lazy** factory: resolves :func:`~clue_locks.get_redis`
  at *first lock acquisition*, not at construction, so building the deep composition needs no active
  ``redis_lifespan`` (the real lock still binds to the process-wide client the moment a run acquires
  it). This is the default ``lock_factory`` for
  :func:`~clue_api.deep.composition.build_deep_phase_handler` so the in-process ``AccountScheduler``
  ships with single-flight **on** rather than silently off.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from clue_core import EntityId
from clue_locks import get_redis
from clue_research.durable import LockFactory, account_entity_lock_factory

__all__ = [
    "build_account_lock_factory",
    "lazy_account_lock_factory",
    "scoped_account_lock_factory",
]


@dataclass
class _AccountLockScope:
    """One physical account-lock lease inherited by awaited child tasks.

    ``active`` is deliberately mutable.  A child task inherits the context tuple, but if it
    outlives the owning context manager it observes ``active=False`` and must acquire a new
    physical lease instead of reusing stale ownership.
    """

    entity_id: EntityId
    active: bool = True


_ACCOUNT_LOCK_SCOPES: ContextVar[tuple[_AccountLockScope, ...]] = ContextVar(
    "clue_account_lock_scopes",
    default=(),
)


class _ScopedAccountLockFactory:
    """Make one physical account lock reentrant within its logical async account unit.

    The fleet scheduler owns the outer Doc C single-flight lease.  Account-agent spend tools are
    allowed to enforce the same invariant when invoked independently, but when invoked inside the
    scheduler they must not deadlock by acquiring that identical Redis lock again.  Context-local
    ownership preserves both properties: unrelated tasks still acquire the physical lock, while
    an awaited nested call for the same account reuses the active lease.
    """

    def __init__(self, inner: LockFactory) -> None:
        self._inner = inner

    def __call__(self, entity_id: EntityId) -> AbstractAsyncContextManager[Any]:
        return self._acquire(entity_id)

    @asynccontextmanager
    async def _acquire(self, entity_id: EntityId) -> AsyncIterator[Any]:
        inherited = _ACCOUNT_LOCK_SCOPES.get()
        if any(scope.active and scope.entity_id == entity_id for scope in inherited):
            yield None
            return

        async with self._inner(entity_id) as lease:
            scope = _AccountLockScope(entity_id=entity_id)
            token = _ACCOUNT_LOCK_SCOPES.set((*inherited, scope))
            try:
                yield lease
            finally:
                # Mark first so a child task that inherited this scope but outlives the parent
                # cannot mistake a released physical lease for current ownership.
                scope.active = False
                _ACCOUNT_LOCK_SCOPES.reset(token)


def scoped_account_lock_factory(lock_factory: LockFactory) -> LockFactory:
    """Return the task-scoped reentrant form of ``lock_factory`` (idempotently)."""

    if isinstance(lock_factory, _ScopedAccountLockFactory):
        return lock_factory
    return _ScopedAccountLockFactory(lock_factory)


def build_account_lock_factory(redis: Any | None = None) -> LockFactory:
    """The eager production :data:`~clue_research.durable.LockFactory` — a Redis in-flight account
    lock per entity (M2.4), resolved **now**. Defaults to the process-wide client
    (:func:`~clue_locks.get_redis`, requires an active ``redis_lifespan``); pass ``redis`` in tests.
    Prefer :func:`lazy_account_lock_factory` at composition sites that build before the lifespan is
    open."""
    return scoped_account_lock_factory(
        account_entity_lock_factory(redis if redis is not None else get_redis())
    )


def lazy_account_lock_factory() -> LockFactory:
    """A :data:`~clue_research.durable.LockFactory` that resolves :func:`~clue_locks.get_redis` at
    the moment a lock is **acquired**, not at construction.

    Constructing the deep composition (:func:`~clue_api.deep.composition.build_deep_phase_handler`)
    must not require an active ``redis_lifespan`` — it happens at import/wiring time — but the lock
    the scheduler enters only fires inside a live deep run, where the lifespan *is* open. So the
    factory defers the ``get_redis()`` read to the per-entity acquisition. Building it, and building
    everything downstream of it, does zero Redis I/O; a missing lifespan surfaces (correctly) only
    if a run actually tries to acquire the lock with no client."""

    def _factory(entity_id: EntityId) -> AbstractAsyncContextManager[Any]:
        # ``get_redis()`` is read here (acquisition time), inside the run's redis_lifespan — not at
        # composition time. ``entity_lock`` still auto-renews under ``async with`` (the M2.4
        # heartbeat), so a long deep run keeps single-flight without lease preemption.
        acquire: Callable[[EntityId], AbstractAsyncContextManager[Any]] = (
            account_entity_lock_factory(get_redis())
        )
        return acquire(entity_id)

    return scoped_account_lock_factory(_factory)
