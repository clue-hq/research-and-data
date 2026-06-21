"""Stage-0 (M5) test harness — a migrated DB + rollback-isolated connections.

Mirrors the claim-store harness (M1): the schema is migrated to head once per session, and each test
runs inside a transaction that is **rolled back**, so tests neither see nor leave each other's rows.
Reuses the M0.3 single-loop runner + reachable-DB probe (DRY). The rollback connection seeds the
core field pack, the client-knowledge field pack (M5.1), and the source manifests — the registry
state the reverse-profiling waterfall reads — inside the same rolled-back transaction.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import load_core_pack
from clue_research.db import db_lifespan
from clue_research.sources import clear_resolver_bindings, seed_source_manifests
from clue_research.stage0 import load_client_knowledge_pack
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
def require_stage0_db(migrated_db: bool) -> None:
    """Skip unless a migrated, reachable database is available."""
    if not migrated_db:
        pytest.skip(
            "CLUE_DATABASE_URL unset or database unreachable; "
            "set it and run `make db-up` to exercise the stage0 tests"
        )


@pytest.fixture
def resolver_bindings() -> Iterator[None]:
    """Clear the in-process resolver bindings before and after a test (binding is module-global)."""
    clear_resolver_bindings()
    yield
    clear_resolver_bindings()


@asynccontextmanager
async def rollback_conn(*, seed: bool = True) -> AsyncIterator[AsyncConnection]:
    """Yield a pooled connection inside a transaction that is always rolled back.

    Seeds the core pack, the client-knowledge pack, and the source manifests (in that order — source
    ``yields`` validate against the field registry) so the reverse-profiling waterfall has real
    manifests to dispatch through."""
    async with db_lifespan() as engine:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            if seed:
                await load_core_pack(conn)
                await load_client_knowledge_pack(conn)
                await seed_source_manifests(conn)
            yield conn
        finally:
            await trans.rollback()
            await conn.close()
