"""Async Redis client lifecycle — the ephemeral-state half of the stack (M2.4).

Redis holds **in-flight locks and rate-limit coordination** (conventions §6); it is explicitly *not*
a source of truth — Postgres is. This module owns the one async Redis client for the process and its
lifecycle, mirroring ``db/engine.py``'s shape: the DSN is read from the ``CLUE_REDIS_URL`` env var
(the shared seam), and ``redis_lifespan`` is the ``@asynccontextmanager`` that opens it on enter and
closes it on exit. The concrete client sits behind these accessors so the backend (a single Redis, a
cluster, or a Temporal activity once durable execution graduates — conventions §2) can be swapped
without touching any caller.

Like ``db/``, this package reads its env var **directly** (not via ``clue_config``) so the
lock layer carries no config dependency; the variable name is the contract.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from redis.asyncio import Redis, from_url

# The shared seam: the Redis DSN is read from this env var (mirrors CLUE_DATABASE_URL for db/).
REDIS_URL_ENV = "CLUE_REDIS_URL"

# Sane local-dev default. db 0; ``decode_responses`` so GET returns ``str`` (token comparison).
DEFAULT_REDIS_URL = "redis://localhost:6379/0"

_client: Redis | None = None


def redis_url() -> str:
    """Return the Redis DSN, from ``CLUE_REDIS_URL`` or the documented local-dev default."""
    return os.environ.get(REDIS_URL_ENV, DEFAULT_REDIS_URL)


def create_redis(url: str | None = None) -> Redis:
    """Create a new async Redis client for ``url`` (``decode_responses=True``).

    Prefer :func:`redis_lifespan` for process-wide lifecycle; this exists for tests and tools that
    want an isolated client. Lock tokens are compared as strings, so responses are decoded here.
    """
    return from_url(url or redis_url(), decode_responses=True)


@asynccontextmanager
async def redis_lifespan(url: str | None = None) -> AsyncIterator[Redis]:
    """Open the process-wide client on enter; close it on exit (the FastAPI-``lifespan`` shape)."""
    global _client
    if _client is not None:  # pragma: no cover - guards against nested/double entry
        raise RuntimeError("redis_lifespan is already active")
    client = create_redis(url)
    _client = client
    try:
        yield client
    finally:
        _client = None
        await client.aclose()


def get_redis() -> Redis:
    """Return the live process-wide client, or raise if no lifespan is active."""
    if _client is None:
        raise RuntimeError("no active Redis client; enter redis_lifespan() first")
    return _client
