"""Claim-store test harness (M1) — a migrated DB + rollback-isolated connections.

These tests exercise the real Postgres substrate (the trigger, CHECK constraints, the merge view,
the field registry), so they need a reachable database. Like the M0.3 DB tests, they
``pytest.skip`` gracefully when ``CLUE_DATABASE_URL`` is unset or the DB is unreachable, so the
default ``make check`` stays green without a database; with `make db-up` + the DSN set, they run.

Isolation model: the schema is migrated to head once per session; each test runs inside a
transaction that is **rolled back** at the end, so tests neither see nor leave each other's rows.
We reuse :func:`run_async` (the ``asyncio.run`` wrapper) and the reachable-DB probe from the M0.3
harness rather than re-implementing them (DRY).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_research.claimstore import load_core_pack

# Reuse the M0.3 helpers: the single-loop coroutine runner and the reachable-DB gate (DRY — these
# are not re-implemented). ``run_async`` is re-exported here for the claim-store test modules.
from tests.db.conftest import _db_available
from tests.db.conftest import run_async as run_async

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return cfg


@pytest.fixture(scope="session")
def migrated_db() -> bool:
    """Migrate to head once per session when a DB is reachable; return whether it is.

    The core field pack is seeded *inside* each test transaction (see :func:`rollback_conn`), not
    committed here — so the claim-store tests stay self-contained and robust even when the M0.3
    migration tests downgrade/upgrade the shared schema mid-session.
    """
    if not _db_available():
        return False
    command.upgrade(_alembic_config(), "head")
    return True


@pytest.fixture
def require_claimstore_db(migrated_db: bool) -> None:
    """Skip unless a migrated, reachable claim store is available."""
    if not migrated_db:
        pytest.skip(
            "CLUE_DATABASE_URL unset or database unreachable; "
            "set it and run `make db-up` to exercise the claim-store tests"
        )


@asynccontextmanager
async def rollback_conn(*, seed_pack: bool = True) -> AsyncIterator[AsyncConnection]:
    """Yield a pooled connection inside a transaction that is always rolled back.

    Use inside a ``run_async`` body. The core field pack is seeded inside this transaction (so
    ``insert_claim`` payload validation finds registered fields) and rolled back with everything
    else — keeping every test isolated and self-contained, and leaving the migrated schema untouched
    for the next test (and a following live ``make db-smoke``). Pass ``seed_pack=False`` to start
    from an empty registry.
    """
    async with db_lifespan() as engine:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            if seed_pack:
                await load_core_pack(conn)
            yield conn
        finally:
            await trans.rollback()
            await conn.close()
