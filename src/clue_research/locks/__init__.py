"""`clue_research.locks` — Redis in-flight locks & rate-limit coordination (M2.4).

The concurrency seam every expensive-work caller uses (substrate §2; conventions §6 — "Redis for
in-flight locks and rate-limit coordination"). It exposes:

* **entity locks** — :func:`entity_lock` / :class:`EntityLock` (atomic acquire, owner-fenced release
  + renew, TTL auto-expiry) and :func:`multi_lock` / :class:`MultiLock` (deadlock-free multi-entity
  acquisition in a deterministic order — the merge path locks both candidates through this).
* **rate limiting** — :class:`RateLimiter`, a shared token bucket per ``source_key`` (resolvers/M4).
* **client lifecycle** — :func:`redis_lifespan` / :func:`get_redis` / :func:`create_redis`, reading
  the DSN from ``CLUE_REDIS_URL`` (the shared seam).

Redis holds **ephemeral state only** — Postgres remains the sole source of truth (conventions §6).
Locks are advisory: they prevent wasted concurrent work; correctness on retry rests on idempotency
keys (substrate §5c) and append-only writes (M1). The implementation is fully hidden behind this
seam, so swapping Redis for another backend (or a Temporal activity) is invisible to callers.
"""

from __future__ import annotations

from clue_research.locks.client import (
    DEFAULT_REDIS_URL,
    REDIS_URL_ENV,
    create_redis,
    get_redis,
    redis_lifespan,
    redis_url,
)
from clue_research.locks.entity_lock import (
    DEFAULT_TTL_MS,
    METRIC_LOCK_ACQUIRED,
    METRIC_LOCK_CONTENDED,
    METRIC_LOCK_RELEASED,
    METRIC_LOCK_RENEWED,
    EntityLock,
    LockTimeout,
    MultiLock,
    entity_lock,
    lock_key,
    multi_lock,
)
from clue_research.locks.rate_limit import RateLimiter

__all__ = [
    # client lifecycle
    "REDIS_URL_ENV",
    "DEFAULT_REDIS_URL",
    "redis_url",
    "create_redis",
    "redis_lifespan",
    "get_redis",
    # entity locks
    "EntityLock",
    "entity_lock",
    "lock_key",
    "MultiLock",
    "multi_lock",
    "LockTimeout",
    "DEFAULT_TTL_MS",
    "METRIC_LOCK_ACQUIRED",
    "METRIC_LOCK_CONTENDED",
    "METRIC_LOCK_RELEASED",
    "METRIC_LOCK_RENEWED",
    # rate limiting
    "RateLimiter",
]
