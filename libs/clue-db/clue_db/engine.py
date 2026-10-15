"""Async engine/pool lifecycle for the Postgres system of record (M0.3).

Postgres is the only source of truth (substrate §12, §13; conventions §6 — "No Airtable or
any external tool in the write path"). This module owns the **one** async engine for the
process and its lifecycle, exposed via the FastAPI-``lifespan`` shape — but built on stdlib
:mod:`contextlib` only, so ``db`` carries **no** web-framework dependency (the ``api/`` layer
wires this engine into FastAPI's ``lifespan`` later, M5/M13).

What lives here (M0.3):

* :func:`database_url` — the DSN, read from the ``CLUE_DATABASE_URL`` env var (the shared seam;
  the local default is documented in this package's ``README.md``). Read directly from the
  environment, **not** via ``clue_config`` — that package is built in parallel and ``db``
  must not depend on it.
* :func:`db_lifespan` — an ``@asynccontextmanager`` that creates the engine on enter and disposes
  it (closing every pooled connection) on exit. This is the FastAPI-``lifespan`` shape.
* :func:`get_engine` — the accessor every persistence-touching milestone uses to reach the live
  engine, and :func:`get_pool` — an alias naming the seam the spec calls out (``get_pool()``).
* :func:`connection` / :func:`transaction` — the session/transaction helpers (M1+ run their
  claim reads/writes through these). **No business queries live here.**

The concrete engine sits behind these accessors so the durable-execution swap (Postgres state
machine → Temporal) changes *where workflow state lives* without touching this DB seam
(substrate §5c, conventions §2/§6).
"""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    create_async_engine,
)

from clue_obs import get_logger
from clue_obs.critical_section import slow_threshold_ms

log = get_logger("clue_db.engine")

# The dependency-injection seam every persistence-touching worker/handler takes: a zero-arg factory
# yielding a connection context manager — :func:`transaction` (commit-on-exit) or :func:`connection`
# in production, a rollback-scoped connection in tests. Declared here once, next to the helpers it
# abstracts over, so every caller injects this one named type instead of re-spelling
# ``Callable[[], AbstractAsyncContextManager[AsyncConnection]]``. The M6 phase handlers, M8
# deep-profiling workers, and M13 review surface all annotate their ``session_factory`` with it.
ConnFactory = Callable[[], AbstractAsyncContextManager[AsyncConnection]]

# The shared seam: the DSN is read from this env var. A parallel agent (M0.4) documents it in
# ``.env.example``; ``db`` only READS it. Kept as a module constant so callers and tests agree;
# its equality with ``config.DB_DSN_ENV_VAR`` is asserted in tests/test_seams.py (the two packages
# can't import each other, so the test is the guard against the spellings drifting).
DATABASE_URL_ENV = "CLUE_DATABASE_URL"

# Sane local-dev default (documented in README.md). asyncpg is the async driver; the DSN names it
# explicitly via the ``+asyncpg`` SQLAlchemy dialect suffix so there is no ambiguity. Matches the
# credentials baked into ``docker-compose.yml``.
DEFAULT_DATABASE_URL = "postgresql+asyncpg://clue:clue@localhost:5432/clue"

# Per-process connection pool (research slowness fix 2026-10-03): explicit settings with the
# SQLAlchemy defaults, read straight from the environment like ``CLUE_DATABASE_URL``.
POOL_SIZE_ENV = "CLUE_DB_POOL_SIZE"
MAX_OVERFLOW_ENV = "CLUE_DB_MAX_OVERFLOW"
POOL_TIMEOUT_ENV = "CLUE_DB_POOL_TIMEOUT_S"


def _env_number(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


# Module-global engine, owned by ``db_lifespan``. There is exactly one engine per process; its
# pool is the connection pool. ``None`` until the lifespan is entered.
_engine: AsyncEngine | None = None


def database_url() -> str:
    """Return the database DSN.

    Read from ``CLUE_DATABASE_URL`` (the shared seam), falling back to the documented local-dev
    default (:data:`DEFAULT_DATABASE_URL`). Read straight from the environment — ``db`` must not
    import ``clue_config`` (it is built in parallel; the env var is the contract between
    them).
    """
    return os.environ.get(DATABASE_URL_ENV, DEFAULT_DATABASE_URL)


def create_engine(url: str | None = None, *, echo: bool = False) -> AsyncEngine:
    """Create a new async engine (and its connection pool) for ``url``.

    Prefer :func:`db_lifespan` for process-wide lifecycle; this exists for tests and tools that
    want an isolated engine. ``value_json`` payloads are passed as already-serialized JSON text by
    the caller (M1) using :func:`clue_core.serialize_value_json`, so no engine-level JSON
    codec is registered here — serialization stays aligned to ``core`` in one place.
    """
    return create_async_engine(
        url or database_url(),
        echo=echo,
        future=True,
        # A cancelled asyncpg cleanup can leave a closed transport behind. Validate pooled
        # connections at checkout so the next fleet claim replaces that connection instead of
        # terminating the worker with InterfaceError("connection is closed").
        pool_pre_ping=True,
        # Behind pgbouncer (transaction mode) a pooled connection holds a real Postgres
        # connection only during a transaction.
        pool_size=int(_env_number(POOL_SIZE_ENV, 5)),
        max_overflow=int(_env_number(MAX_OVERFLOW_ENV, 10)),
        pool_timeout=_env_number(POOL_TIMEOUT_ENV, 30),
    )


@asynccontextmanager
async def db_lifespan(url: str | None = None, *, echo: bool = False) -> AsyncIterator[AsyncEngine]:
    """Create the process-wide engine on enter; dispose it (close the pool) on exit.

    The FastAPI-``lifespan`` shape, expressed with stdlib :mod:`contextlib` so ``db`` stays
    framework-free. On exit, :meth:`AsyncEngine.dispose` closes every pooled connection, so a
    clean shutdown leaks nothing (verified by ``tests/test_db_engine.py``)::

        async with db_lifespan():
            ...  # get_engine() is live here
        # engine disposed; get_engine() raises again
    """
    global _engine
    if _engine is not None:  # pragma: no cover - guards against nested/double entry
        raise RuntimeError("db_lifespan is already active; nest connection()/transaction() instead")
    engine = create_engine(url, echo=echo)
    _engine = engine
    try:
        yield engine
    finally:
        _engine = None
        await engine.dispose()


def get_engine() -> AsyncEngine:
    """Return the live process-wide engine, or raise if no lifespan is active.

    The accessor every persistence-touching milestone uses. Raising (rather than lazily creating)
    keeps engine ownership in :func:`db_lifespan` alone, so there is one well-defined open/close.
    """
    if _engine is None:
        raise RuntimeError(
            "no active database engine; enter db_lifespan() (or the FastAPI lifespan) first"
        )
    return _engine


def get_pool() -> AsyncEngine:
    """Alias for :func:`get_engine` — the ``get_pool()`` accessor the spec names (§M0.3).

    SQLAlchemy's :class:`AsyncEngine` *is* the pool owner; the connection pool is reached through
    it. The name mirrors the spec's "single DB access contract (``get_pool()``/session
    dependency)".
    """
    return get_engine()


@asynccontextmanager
async def connection() -> AsyncIterator[AsyncConnection]:
    """Yield a pooled connection (autocommit-off), returned to the pool on exit.

    No surrounding transaction is begun — use :func:`transaction` when you want one. M1+ run reads
    through here. No business queries live in ``db``.
    """
    started = time.monotonic()
    async with get_engine().connect() as conn:
        _report_wait(started)
        yield conn


def _report_wait(started: float) -> None:
    """Log a connection that took long to get (W2-15 option B).

    Every connection a process uses comes from one small pool, shared by its jobs, its agent
    bookkeeping and its fleet heartbeat; a heartbeat that cannot get one in time loses its lease.
    A wait at or above ``CLUE_DB_CRITICAL_SECTION_LOG_MS`` is logged with the pool's state. The
    wait includes the checkout's liveness ping and, for a transaction, its ``BEGIN``.
    """
    waited_ms = (time.monotonic() - started) * 1000
    if waited_ms >= slow_threshold_ms():
        log.info(
            "db.connection_waited",
            wait_ms=round(waited_ms, 1),
            pool=get_engine().pool.status(),
        )


@asynccontextmanager
async def transaction() -> AsyncIterator[AsyncConnection]:
    """Yield a connection inside a transaction; commit on success, roll back on error.

    The session/transaction helper the spec calls out (§M0.3). The append-only claim store (M1)
    writes new claim rows (and sets ``superseded_by`` on the row being superseded) through this, so
    a supersession is one atomic unit — never an in-place UPDATE of a value column.
    """
    started = time.monotonic()
    async with get_engine().begin() as conn:
        _report_wait(started)
        yield conn


@asynccontextmanager
async def repeatable_read_transaction() -> AsyncIterator[AsyncConnection]:
    """Yield one read-only, repeatable-read transaction for deterministic projections."""

    started = time.monotonic()
    async with get_engine().connect() as conn:
        _report_wait(started)
        await conn.execution_options(isolation_level="REPEATABLE READ")
        async with conn.begin():
            await conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            yield conn
