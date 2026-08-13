"""Source-registry test harness (M4.2) — a migrated DB + rollback-isolated connections.

Mirrors the M3.3 / claim-store harness (DRY: reuses the M0.3 reachable-DB probe + ``run_async``).
The schema is migrated to head once per session; each test runs inside a transaction that is always
rolled back, so tests never see or leave each other's ``source_manifest`` rows. DB-needing tests
``pytest.skip`` when ``CLUE_DATABASE_URL`` is unset/unreachable, keeping ``make check`` green.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_research.claimstore import load_core_pack
from clue_research.sources import clear_resolver_bindings
from clue_research.stage0 import load_client_knowledge_pack

# Reuse the M0.3 helpers (DRY). ``run_async`` is re-exported for the source test modules.
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
def require_db(migrated_db: bool) -> None:
    """Skip unless a migrated, reachable DB is available."""
    if not migrated_db:
        pytest.skip(
            "CLUE_DATABASE_URL unset or database unreachable; "
            "set it and run a per-branch DB container to exercise the source-registry tests"
        )


@pytest.fixture(autouse=True)
def _isolate_resolver_bindings() -> Iterator[None]:
    """Clear the in-process resolver-binding map around every test (it is module-global)."""
    clear_resolver_bindings()
    yield
    clear_resolver_bindings()


@asynccontextmanager
async def rollback_conn(*, seed_core: bool = True) -> AsyncIterator[AsyncConnection]:
    """Yield a pooled connection inside a transaction that is always rolled back.

    Defaults to seeding the M1 core pack (so the seed manifests' ``yields`` resolve against real
    ``core.*`` / ``account.*`` fields); pass ``seed_core=False`` to skip it.
    """
    async with db_lifespan() as engine:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            if seed_core:
                await load_core_pack(conn)
                await load_client_knowledge_pack(conn)
            yield conn
        finally:
            await trans.rollback()
            await conn.close()
