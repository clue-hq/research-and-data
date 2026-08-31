"""M4.4 resolver test harness — a migrated DB + rollback-isolated connections + backend doubles.

Mirrors the M4.2/M4.1 source-registry harness (DRY: reuses the M0.3 DB probe + ``run_async``
and the same rollback-per-test isolation). ``rollback_conn`` also seeds the **source manifests**
so every resolver's ``source_key`` is registered for the waterfall to dispatch through. DB-needing
tests ``pytest.skip`` when ``CLUE_DATABASE_URL`` is unset/unreachable, keeping ``make check`` green.

The doubles here are the whole point of the hermetic-CI rule (locked decision #3): a resolver's
provider-specific :class:`~clue_research.resolvers.base.EnrichmentBackend` is replaced with a
counting / raising / empty double, so the resolver + waterfall are exercised end to end without a
single live provider call or credential.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import Entity, FieldDef, RetryableResolverError
from clue_db import db_lifespan
from clue_research.adapters import clear_adapters
from clue_research.claimstore import load_core_pack
from clue_research.resolvers.base import ResolvedField
from clue_research.sources import clear_resolver_bindings, seed_source_manifests
from clue_research.stage0 import load_client_knowledge_pack

# Reuse the M0.3 helpers (DRY). ``run_async`` is re-exported for the resolver test modules.
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
            "set it and run a per-branch DB container to exercise the resolver tests"
        )


@pytest.fixture(autouse=True)
def _isolate_resolver_bindings() -> Iterator[None]:
    """Clear the in-process resolver-binding AND adapter-registry maps around every test (both are
    module-global; M4.5's ``register_scrape_resolver`` registers the ``firecrawl_html`` adapter)."""
    clear_resolver_bindings()
    clear_adapters()
    yield
    clear_resolver_bindings()
    clear_adapters()


@asynccontextmanager
async def rollback_conn() -> AsyncIterator[AsyncConnection]:
    """Yield a pooled connection in an always-rolled-back transaction, with the core pack + source
    manifests seeded (so resolver ``source_key``\\s resolve and their ``yields`` validate)."""
    async with db_lifespan() as engine:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            await load_core_pack(conn)
            await load_client_knowledge_pack(conn)
            await seed_source_manifests(conn)
            yield conn
        finally:
            await trans.rollback()
            await conn.close()


# --- backend doubles (the hermetic provider seam) ---------------------------


class CountingBackend:
    """An :class:`EnrichmentBackend` double: returns preset answers and counts ``fetch`` calls.

    The fields it returns are entity-agnostic (the resolver injects the entity), so the same double
    serves whatever entity the waterfall hands it — exactly how a real provider would answer a
    domain query. The call counter proves the waterfall's stop-at-first-confident / swap behavior.
    """

    def __init__(self, fields: Sequence[ResolvedField]) -> None:
        self._fields = list(fields)
        self.calls = 0

    def fetch(self, entity: Entity, field: FieldDef) -> Sequence[ResolvedField]:
        self.calls += 1
        return list(self._fields)


class RaisingBackend:
    """A backend double whose ``fetch`` raises a transient fault (the retryable-failure path)."""

    def __init__(self, exc: Exception | None = None) -> None:
        self._exc = exc or RetryableResolverError("simulated transient provider failure")
        self.calls = 0

    def fetch(self, entity: Entity, field: FieldDef) -> Sequence[ResolvedField]:
        self.calls += 1
        raise self._exc
