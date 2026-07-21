"""Memory-substrate test harness (PB-B3) — migrated DB + rollback-isolated connections.

Mirrors the spine harness (DRY: reuses the M0.3 reachable-DB probe and ``run_async``). Tests
exercise the substrate through the two seams; direct ``_store`` access here is *test setup only*
(simulating states like an approved ``agent_observed`` record whose review-queue producer is
Phase C) — production code outside ``clue_memory`` can never do this (Rules S1/S3 + the
seam-guard test).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config import MemoryCaps, Settings, load_settings
from clue_core import (
    MemoryProvenanceClass,
    MemoryScopeType,
    MemorySubmission,
    MemoryType,
    ReconcileCandidate,
    ReconcileJudgment,
    ScopeRef,
)
from clue_db import db_lifespan
from clue_spine import create_brand, create_product, create_project, create_workspace
from tests.db.conftest import _db_available
from tests.db.conftest import run_async as run_async

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return cfg


@pytest.fixture(scope="session")
def migrated_db() -> bool:
    if not _db_available():
        return False
    command.upgrade(_alembic_config(), "head")
    return True


@pytest.fixture
def require_memory_db(migrated_db: bool) -> None:
    if not migrated_db:
        pytest.skip(
            "CLUE_DATABASE_URL unset or database unreachable; "
            "set it and run `make db-up` to exercise the memory tests"
        )


@asynccontextmanager
async def rollback_conn() -> AsyncIterator[AsyncConnection]:
    """Yield a pooled connection inside a transaction that is always rolled back."""
    async with db_lifespan() as engine:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            yield conn
        finally:
            await trans.rollback()
            await conn.close()


# --- fixtures over the spine + research tables ------------------------------


async def seed_account(
    conn: AsyncConnection,
    *,
    workspace_id: str | None,
    brand_id: str | None = None,
    canonical_name: str = "Company X",
) -> UUID:
    """A workspace-local ``account_entity`` (founder ruling 2026-07-22). ``workspace_id=None``
    seeds a legacy/global account that cannot own workspace-scoped memory (the fail-closed case).
    Raw SQL: the research-side writer that stamps workspace/brand is future work."""
    account_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO account_entity (id, canonical_name, workspace_id, brand_id) "
            "VALUES (:id, :name, :workspace_id, :brand_id)"
        ),
        {
            "id": account_id,
            "name": canonical_name,
            "workspace_id": workspace_id,
            "brand_id": brand_id,
        },
    )
    return account_id


async def seed_spine(conn: AsyncConnection, tag: str = "") -> SimpleNamespace:
    """A workspace with brand, product, project, and a workspace-local account — the scope tree
    a memory attaches to."""
    ws = await create_workspace(conn, name=f"Acme{tag}")
    brand = await create_brand(conn, workspace_id=ws.workspace_id, name=f"Acme Brand{tag}")
    product = await create_product(
        conn, brand_id=brand.brand_id, workspace_id=ws.workspace_id, name=f"Widget{tag}"
    )
    project = await create_project(
        conn, workspace_id=ws.workspace_id, brand_id=brand.brand_id, name=f"Q3 ABM{tag}"
    )
    account_id = await seed_account(
        conn,
        workspace_id=ws.workspace_id,
        brand_id=brand.brand_id,
        canonical_name=f"Company X{tag}",
    )
    return SimpleNamespace(
        workspace_id=ws.workspace_id,
        brand_id=brand.brand_id,
        product_id=product.product_id,
        project_id=project.project_id,
        account_entity_id=account_id,
    )


async def seed_contact(conn: AsyncConnection) -> UUID:
    """A resolved contact entity (the subject-binding key)."""
    account_id = uuid4()
    await conn.execute(
        text("INSERT INTO account_entity (id, canonical_name) VALUES (:id, :name)"),
        {"id": account_id, "name": f"Account {account_id.hex[:8]}"},
    )
    contact_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO contact_entity (id, account_entity_id, full_name) "
            "VALUES (:id, :account_id, :name)"
        ),
        {"id": contact_id, "account_id": account_id, "name": "Jordan Rivers"},
    )
    return contact_id


async def seed_claim(conn: AsyncConnection) -> UUID:
    """A minimal claim row for memory_claim_ref FKs."""
    account_id = uuid4()
    await conn.execute(
        text("INSERT INTO account_entity (id, canonical_name) VALUES (:id, :name)"),
        {"id": account_id, "name": f"Account {account_id.hex[:8]}"},
    )
    claim_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO claim (id, entity_id, entity_type, field_key, value_json, source_tier, "
            "extraction_method, confidence, run_id, research_mode) "
            "VALUES (:id, :entity_id, 'account', 'core.employee_count', '100'::jsonb, 1, "
            "'api', 0.9, :run_id, 'account_profiling')"
        ),
        {"id": claim_id, "entity_id": account_id, "run_id": uuid4()},
    )
    return claim_id


# --- seam construction helpers ----------------------------------------------


def make_settings(**overrides: object) -> Settings:
    return load_settings(_env_file=None, **overrides)


def make_caps(**overrides: object) -> MemoryCaps:
    return MemoryCaps(**overrides)  # type: ignore[arg-type]


def submission(
    workspace_id: str,
    *,
    scope_type: MemoryScopeType = MemoryScopeType.BRAND,
    scope_id: str | None = None,
    body: str = "Never use fear-based hooks.",
    type_: MemoryType = MemoryType.PREFERENCE,
    trigger: str = "when writing outreach",
    provenance: MemoryProvenanceClass = MemoryProvenanceClass.USER_STATED,
    claim_refs: tuple[UUID, ...] = (),
    subject_entity_id: UUID | None = None,
) -> MemorySubmission:
    return MemorySubmission(
        workspace_id=workspace_id,
        scope=ScopeRef(scope_type=scope_type, scope_id=scope_id),
        type=type_,
        trigger=trigger,
        body=body,
        provenance_class=provenance,
        claim_refs=claim_refs,
        subject_entity_id=subject_entity_id,
    )


class ScriptedJudge:
    """A :class:`~clue_core.ReconcileJudge` returning a scripted judgment (records calls)."""

    def __init__(self, judgment: ReconcileJudgment) -> None:
        self.judgment = judgment
        self.calls: list[tuple[MemorySubmission, tuple[ReconcileCandidate, ...]]] = []

    async def judge(
        self, submission: MemorySubmission, candidates: tuple[ReconcileCandidate, ...]
    ) -> ReconcileJudgment:
        self.calls.append((submission, candidates))
        return self.judgment


class RaisingJudge:
    """A judge that always fails — exercises the parked-``proposed`` fail-safe, and doubles as
    proof a code path never consulted the judge at all (no exception ⇒ no call)."""

    def __init__(self) -> None:
        self.calls = 0

    async def judge(
        self, submission: MemorySubmission, candidates: tuple[ReconcileCandidate, ...]
    ) -> ReconcileJudgment:
        self.calls += 1
        raise RuntimeError("judge unavailable")


def add_judge() -> ScriptedJudge:
    from clue_core import ReconcileVerdictKind

    return ScriptedJudge(
        ReconcileJudgment(verdict=ReconcileVerdictKind.ADD, rationale="scripted add")
    )
