"""`clue_research.db` — Postgres + pgvector + migrations (M0.3).

The shared persistence layer and the **single DB access contract** every persistence-touching
milestone consumes (conventions §2; substrate §12 — "Postgres is the only source of truth; no
Airtable in the write path"). The Alembic migrations workflow (under ``alembic/`` at the repo
root) is the *only* path that mutates schema — no component issues DDL at runtime.

This package owns the async engine/pool lifecycle and the session/transaction helpers; it owns
**no** domain tables and **no** business queries (those land in M1+). JSONB ``value_json``
serialization is aligned to ``clue_core`` (M0.2) and is performed there, not re-implemented
here. ``db`` reads its DSN from the ``CLUE_DATABASE_URL`` env var and must not import
``clue_research.config`` (built in parallel; the env var is the contract between them).

Implements ENG-114 (docs/specs/M00-foundations-and-shared-contracts.md §M0.3).
"""

from __future__ import annotations

from clue_research.db.engine import (
    DATABASE_URL_ENV,
    DEFAULT_DATABASE_URL,
    ConnFactory,
    connection,
    create_engine,
    database_url,
    db_lifespan,
    get_engine,
    get_pool,
    transaction,
)

__all__ = [
    "DATABASE_URL_ENV",
    "DEFAULT_DATABASE_URL",
    "ConnFactory",
    "database_url",
    "create_engine",
    "db_lifespan",
    "get_engine",
    "get_pool",
    "connection",
    "transaction",
]
