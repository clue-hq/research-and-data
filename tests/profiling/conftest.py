"""Test doubles + the DB harness for M8 deep profiling (M8.3 committee, M8.4 contact).

Pure (no-DB) tests cover the role/use-class/binding logic, the stopping rule, and coverage; the
worker/admission/field-pack tests use a migrated DB + rollback-isolated connections (mirroring the
claim-store / discovery harness) and ``pytest.skip`` without a reachable DB so ``make check`` stays
green. Async code is driven from sync test bodies via ``run_async``. The doubles model the seams a
real committee run depends on: a grounded :class:`CommitteeSource` and the :class:`LLMGateway`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import load_core_pack
from clue_research.core import (
    AccountEntity,
    Completion,
    Confidence,
    CostCents,
    EmbeddingResult,
    EntityId,
    ICPCreatedFrom,
    ICPSpec,
    Message,
)
from clue_research.db import db_lifespan
from clue_research.identity import get_account, insert_account_entity
from clue_research.profiling.committee import load_committee_pack
from clue_research.profiling.committee.sources import CommitteePersonCandidate
from clue_research.profiling.fields import load_deep_profiling_pack

# Reuse the M0.3 helpers (DRY): the single-loop coroutine runner + the reachable-DB gate.
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
def require_profiling_db(migrated_db: bool) -> None:
    """Skip unless a migrated, reachable DB is available (so ``make check`` stays green w/o one)."""
    if not migrated_db:
        pytest.skip(
            "CLUE_DATABASE_URL unset or database unreachable; "
            "set it and run `make db-up` to exercise the M8 profiling DB tests"
        )


@asynccontextmanager
async def rollback_conn() -> AsyncIterator[AsyncConnection]:
    """Yield a pooled connection inside an always-rolled-back transaction (per-test isolation)."""
    async with db_lifespan() as engine:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            yield conn
        finally:
            await trans.rollback()
            await conn.close()


async def seed_packs(conn: AsyncConnection) -> None:
    """Register the field packs the profiling tests need (idempotent): the core pack + the M8 seed
    (resonance/facet) + the M8.3 committee pack."""
    await load_core_pack(conn)
    await load_deep_profiling_pack(conn)
    await load_committee_pack(conn)


async def insert_test_account(
    conn: AsyncConnection, *, name: str = "Acme Robotics", domain: str | None = "acme.example"
) -> AccountEntity:
    """Insert a resolved account entity and return its full record (the committee's parent)."""
    account_id = await insert_account_entity(conn, canonical_name=name, primary_domain=domain)
    account = await get_account(conn, account_id)
    assert account is not None
    return account


def icp_spec() -> ICPSpec:
    """A minimal in-memory ICP spec (committee discovery reads org context, not the rubric)."""
    return ICPSpec(
        client_id="acme",
        icp_key="default",
        created_from=ICPCreatedFrom.SYNTHESIS,
    )


def make_candidate(
    *,
    source_key: str = "apollo_people",
    linkedin_url: str | None = None,
    verified_email: str | None = None,
    full_name: str | None = None,
    title: str | None = None,
    source_url: str | None = None,
    matched_signal: str = "leadership page",
    discovery_confidence: Confidence = 0.8,
    cost_cents: CostCents = Decimal(0),
) -> CommitteePersonCandidate:
    """Build a grounded committee candidate (the shape a real source returns)."""
    return CommitteePersonCandidate(
        source_key=source_key,
        linkedin_url=linkedin_url,
        verified_email=verified_email,
        full_name=full_name,
        title=title,
        source_url=source_url,
        matched_signal=matched_signal,
        discovery_confidence=discovery_confidence,
        cost_cents=cost_cents,
    )


@dataclass
class FakeCommitteeSource:
    """A :class:`CommitteeSource` double: returns its canned candidates and counts calls (so a test
    can assert bounded querying / provider-swap behaviour)."""

    source_key: str
    tier: int
    candidates: list[CommitteePersonCandidate] = field(default_factory=list)
    calls: int = 0

    async def find_candidates(
        self, account: AccountEntity, *, limit: int
    ) -> Sequence[CommitteePersonCandidate]:
        self.calls += 1
        return list(self.candidates[:limit])


@dataclass
class FakeGateway:
    """An :class:`LLMGateway` double: ``complete`` returns a canned (configurable) reply so the role
    parser's success path is exercised; ``embed`` is unused. ``complete_calls`` lets a test assert
    role inference ran. The real ``StubGateway`` (non-JSON output) covers the fail-safe path."""

    reply: str = '{"role": "economic_buyer", "confidence": 0.9, "rationale": "CFO has budget"}'
    cost_cents: CostCents = Decimal(0)
    complete_calls: int = 0

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        self.complete_calls += 1
        return Completion(model=model, text=self.reply, cost_cents=self.cost_cents)

    def embed(self, *, model: str, inputs: list[str]) -> EmbeddingResult:
        return EmbeddingResult(model=model, vectors=())


__all__ = [
    "run_async",
    "rollback_conn",
    "migrated_db",
    "require_profiling_db",
    "seed_packs",
    "insert_test_account",
    "icp_spec",
    "make_candidate",
    "FakeCommitteeSource",
    "FakeGateway",
    "EntityId",
]
