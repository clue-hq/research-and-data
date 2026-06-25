"""M10 compliance test harness — a migrated DB + rollback-isolated connections.

Mirrors the M9 verification harness (`tests/verification/conftest.py`): the schema is migrated to
head once per session; each test runs inside an always-rolled-back transaction, so tests neither see
nor leave each other's rows. The core field pack, the **M10 compliance pack** (so
``contact.jurisdiction`` is registered), and a few *test-only* fields — representative location
fields (so the jurisdiction resolver's claim-path can be exercised) and a governed
``contact.facet.*`` hook (so the M10.3 use-gate can be exercised over a real personal claim) — are
loaded inside the transaction. M8/M1 own the real location/facet field-keys; here we register
representative rows. DB tests ``pytest.skip`` gracefully without a reachable database, so
``make check`` stays green without one.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import SeedField, load_core_pack, load_pack
from clue_research.compliance import load_compliance_pack
from clue_research.core import FieldDef, PassKind, ReuseScope
from clue_research.db import db_lifespan
from tests.db.conftest import _db_available
from tests.db.conftest import run_async as run_async

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Test-only fields M10 reads. M8/M1 own the real location/facet field-keys; here we register
# representative rows so the M10.1 resolver claim-path and the M10.3 use-gate (which gates a real
# governed contact.facet.* personal claim) are testable.
_TEST_FIELD_PACK: tuple[SeedField, ...] = (
    SeedField(
        field_def=FieldDef(
            field_key="contact.location",
            value_type="object",
            freshness_ttl=timedelta(days=180),
            pass_kind=PassKind.DEEP,
            reuse_scope=ReuseScope.TENANT_PRIVATE,
        ),
        value_schema={"type": "object"},
        description="Test-only contact location field (M10.1 resolver claim-path).",
    ),
    SeedField(
        field_def=FieldDef(
            field_key="account.hq_location",
            value_type="object",
            freshness_ttl=timedelta(days=180),
            pass_kind=PassKind.SCORING,
            reuse_scope=ReuseScope.PUBLIC_FOOTPRINT,
        ),
        value_schema={"type": "object"},
        description="Test-only account HQ location field (M10.1 resolver claim-path).",
    ),
    SeedField(
        field_def=FieldDef(
            field_key="contact.facet.test_hook",
            value_type="string",
            freshness_ttl=timedelta(days=90),
            pass_kind=PassKind.DEEP,
            # contact.facet.* is FieldClass.CONTACT_FACET → TENANT_PRIVATE by default; declared
            # explicitly. A claim on it requires both identity_binding + use_class (the Claim
            # validator + DB CHECK), which is exactly what the M10.3 gate reads.
            reuse_scope=ReuseScope.TENANT_PRIVATE,
        ),
        value_schema={"type": "string"},
        description="Test-only governed contact personal-hook field (M10.3 use-gate path).",
    ),
)


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
def require_compliance_db(migrated_db: bool) -> None:
    """Skip unless a migrated, reachable database is available."""
    if not migrated_db:
        pytest.skip(
            "CLUE_DATABASE_URL unset or database unreachable; "
            "set it and run `make db-up` to exercise the compliance tests"
        )


@asynccontextmanager
async def rollback_conn() -> AsyncIterator[AsyncConnection]:
    """Yield a pooled connection inside an always-rolled-back transaction, with the core pack, the
    M10 compliance pack, and the test-only location/facet fields loaded so M10's reads work."""
    async with db_lifespan() as engine:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            await load_core_pack(conn)
            await load_compliance_pack(conn)
            await load_pack(conn, _TEST_FIELD_PACK)
            yield conn
        finally:
            await trans.rollback()
            await conn.close()
