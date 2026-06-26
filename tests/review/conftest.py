"""M13 review test harness — the migrated-DB gate, rollback conn, and enum-parity helper.

Mirrors the durable / claim-store harness (DRY): reuses the M0.3 single-loop ``run_async`` +
reachable-DB probe, migrates to head once per session, and yields a rolled-back connection seeded
with the M1 core pack. Covers all three Wave-1 surfaces in this package:

* M13.1 surface / projection / gate tests and M13.2 disposition tables + ``labeled_dataset`` view run
  against real Postgres (the tables + view are SQL), so they ``pytest.skip`` when no DB is reachable.
* M13.4 observability-panel logic runs entirely on in-memory reader fakes (no database) and stays in
  the default ``make check``; only its seam tests (``cost_estimate`` snapshot,
  ``claimstore.claims_for_runs``, per-source-yield equality) need the DB gate.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
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
    """Skip unless a migrated, reachable database (with the review tables) is available."""
    if not migrated_db:
        pytest.skip(
            "CLUE_DATABASE_URL unset or database unreachable; "
            "set it and run `make db-up` to exercise the review DB tests"
        )


@asynccontextmanager
async def rollback_conn(*, seed_pack: bool = True) -> AsyncIterator[AsyncConnection]:
    """Yield a pooled connection inside a transaction that is always rolled back (test isolation).

    The core field pack is seeded inside the transaction (so ``insert_claim`` payload validation
    finds registered fields, and the ``account.scoring.*`` fields exist for the ``labeled_dataset``
    join) and rolled back with everything else.
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


async def enum_labels(conn: AsyncConnection, typname: str) -> list[str]:
    """The Postgres enum's labels in definition order (the enum-parity comparison)."""
    rows = await conn.execute(
        text(
            "SELECT e.enumlabel FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid "
            "WHERE t.typname = :t ORDER BY e.enumsortorder"
        ),
        {"t": typname},
    )
    return [r[0] for r in rows.all()]
