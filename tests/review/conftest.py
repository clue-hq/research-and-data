"""Review (M13) test harness — pure unit tests + a migrated-DB gate.

The M13.4 observability-surface logic runs entirely on in-memory reader fakes (no database), so the
panel projection / threshold-alert / honesty-guarantee tests are pure. The seam tests that exercise
real Postgres (the ``cost_estimate`` snapshot, ``claimstore.claims_for_runs``, the per-source-yield
equality) need a reachable DB and ``pytest.skip`` when none is configured — reusing the M0.3
``run_async`` + reachable-DB probe and the claim-store rollback-isolation pattern (DRY), so the
default ``make check`` stays green without a database.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import load_core_pack
from clue_research.db import db_lifespan

# Reuse the M0.3 single-loop coroutine runner + reachable-DB gate (DRY).
from tests.db.conftest import _db_available
from tests.db.conftest import run_async as run_async

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return cfg


@pytest.fixture(scope="session")
def migrated_db() -> bool:
    """Migrate to head once per session when a DB is reachable; return whether it is."""
    if not _db_available():
        return False
    command.upgrade(_alembic_config(), "head")
    return True


@pytest.fixture
def require_review_db(migrated_db: bool) -> None:
    """Skip unless a migrated, reachable database is available."""
    if not migrated_db:
        pytest.skip(
            "CLUE_DATABASE_URL unset or database unreachable; "
            "set it and run `make db-up` to exercise the review DB tests"
        )


@asynccontextmanager
async def rollback_conn(*, seed_pack: bool = True) -> AsyncIterator[AsyncConnection]:
    """Yield a pooled connection inside a transaction that is always rolled back (test isolation).

    The core field pack is seeded inside the transaction (so ``insert_claim`` payload validation
    finds registered fields) and rolled back with everything else."""
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
