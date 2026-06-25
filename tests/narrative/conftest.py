"""M12 narrative test harness — a migrated DB + rollback-isolated connections.

The positioner's behaviour is exercised against the real Postgres substrate (the field registry, the
merge view, the ``claim_support`` / ``positioning_policy`` side tables, the ``faithfulness_verdict``
cache the real judge writes), so these tests need a reachable database and skip gracefully without
one — like the M9 suites, so ``make check`` stays green with no DB. The pure machinery (prompt
assembly, response parsing, the field-def / policy shapes) runs in ``make check`` with no DB.

Isolation: the schema is migrated to head once per session; each test runs inside a transaction that
is **rolled back**. The core field pack *and* the M12 narrative pack are loaded inside the txn so
the merge/registry lookups find the account fields and ``account.value_narrative``.
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
from clue_research.narrative import load_narrative_pack
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
def require_narrative_db(migrated_db: bool) -> None:
    """Skip unless a migrated, reachable database is available."""
    if not migrated_db:
        pytest.skip(
            "CLUE_DATABASE_URL unset or database unreachable; "
            "set it and run `make db-up` to exercise the narrative tests"
        )


@asynccontextmanager
async def rollback_conn() -> AsyncIterator[AsyncConnection]:
    """Yield a pooled connection inside an always-rolled-back transaction, with the core field pack
    and the M12 narrative pack loaded so the merge view and ``account.value_narrative`` resolve."""
    async with db_lifespan() as engine:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            await load_core_pack(conn)
            await load_narrative_pack(conn)
            yield conn
        finally:
            await trans.rollback()
            await conn.close()
