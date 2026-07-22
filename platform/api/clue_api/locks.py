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

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from clue_core import EntityId
from clue_locks import get_redis
from clue_research.durable import LockFactory, account_entity_lock_factory

__all__ = ["build_account_lock_factory", "lazy_account_lock_factory"]


def build_account_lock_factory(redis: Any | None = None) -> LockFactory:
    """The eager production :data:`~clue_research.durable.LockFactory` — a Redis in-flight account
    lock per entity (M2.4), resolved **now**. Defaults to the process-wide client
    (:func:`~clue_locks.get_redis`, requires an active ``redis_lifespan``); pass ``redis`` in tests.
    Prefer :func:`lazy_account_lock_factory` at composition sites that build before the lifespan is
    open."""
    return account_entity_lock_factory(redis if redis is not None else get_redis())


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

    return _factory
