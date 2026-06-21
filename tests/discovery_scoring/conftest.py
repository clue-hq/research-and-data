"""Test doubles + helpers for M6 discovery (ENG-128 M6.1) and the admission gate (ENG-133 M6.2).

M6.1 discovery is pure of persistence (channels are providers, dedup uses the M2 normalizers, the
ICP spec is built in-memory). M6.2 admission writes to the store (resolve / disposition / claims),
so its tests use a migrated DB + rollback-isolated connections (mirroring the claim-store harness);
both drive async code from a sync body via ``run_async``. The doubles model the seams a real run
depends on: a grounded :class:`DiscoveryChannel`, the :class:`LLMGateway`, and a candidate stream.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.core import (
    Completion,
    EmbeddingResult,
    EntityId,
    ICPCreatedFrom,
    ICPSpec,
    Message,
)
from clue_research.db import db_lifespan
from clue_research.discovery_scoring.discovery import (
    CandidateHypothesis,
    CandidateRecord,
    DiscoveryQuery,
)

# Reuse the M0.3 helpers (DRY): the single-loop coroutine runner + the reachable-DB gate.
from tests.db.conftest import _db_available
from tests.db.conftest import run_async as run_async

Responder = Callable[[DiscoveryQuery], Sequence[CandidateRecord]]

_REPO_ROOT = Path(__file__).resolve().parents[2]


# --- M6.2: candidate stream + the migrated-DB rollback harness ----------------
def candidate(
    *,
    matched_channel: str = "exa",
    record_ref: str = "rec:1",
    domain: str | None = None,
    name: str | None = None,
    url: str | None = None,
    signal: str = "series-b saas",
    confidence: float = 0.8,
    cost_cents: Decimal = Decimal(0),
    seed_entity_id: EntityId | None = None,
) -> CandidateHypothesis:
    """Build a grounded :class:`CandidateHypothesis` (the M6.1 output the gate admits)."""
    return CandidateHypothesis(
        matched_channel=matched_channel,
        source_record_ref=record_ref,
        source_url=url,
        candidate_domain=domain,
        raw_name=name,
        matched_signal=signal,
        resolver_confidence=confidence,
        cost_cents=cost_cents,
        seed_entity_id=seed_entity_id,
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
def require_discovery_db(migrated_db: bool) -> None:
    """Skip unless a migrated, reachable DB is available (so ``make check`` stays green w/o one)."""
    if not migrated_db:
        pytest.skip(
            "CLUE_DATABASE_URL unset or database unreachable; "
            "set it and run `make db-up` to exercise the M6.2 admission tests"
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


def icp_spec(discovery_strategy: dict[str, JsonValue] | None = None) -> ICPSpec:
    """Build an in-memory ICP spec carrying a discovery-strategy slot (the only field M6.1 uses)."""
    return ICPSpec(
        client_id="acme",
        icp_key="default",
        created_from=ICPCreatedFrom.SYNTHESIS,
        discovery_strategy=discovery_strategy or {},
    )


def record(
    ref: str,
    *,
    domain: str | None = None,
    name: str | None = None,
    url: str | None = None,
    signal: str = "icp-match",
    confidence: float = 0.8,
    cost_cents: Decimal = Decimal(0),
) -> CandidateRecord:
    """Build one grounded candidate record (the shape a real channel returns)."""
    return CandidateRecord(
        source_record_ref=ref,
        source_url=url,
        candidate_domain=domain,
        raw_name=name,
        matched_signal=signal,
        confidence=confidence,
        cost_cents=cost_cents,
    )


@dataclass
class FakeChannel:
    """A :class:`DiscoveryChannel` double: returns whatever ``responder`` computes for a query and
    records every call (so tests can assert fan-out + provider-swap behaviour)."""

    source_key: str
    responder: Responder
    calls: list[DiscoveryQuery] = field(default_factory=list)

    async def discover(self, query: DiscoveryQuery) -> list[CandidateRecord]:
        self.calls.append(query)
        return list(self.responder(query))


def const_channel(source_key: str, records: Sequence[CandidateRecord]) -> FakeChannel:
    """A channel that returns the same records on every call."""
    return FakeChannel(source_key=source_key, responder=lambda _query: records)


def empty_channel(source_key: str) -> FakeChannel:
    """A channel that always returns nothing (a real channel's miss) — never fabricates."""
    return FakeChannel(source_key=source_key, responder=lambda _query: ())


@dataclass
class FakeGateway:
    """An :class:`LLMGateway` double: ``complete`` returns canned query lines (never entities);
    ``embed`` is unused by discovery. ``complete_calls`` lets a test assert planning ran."""

    reply: str = "widen query one\nwiden query two"
    complete_calls: int = 0

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        self.complete_calls += 1
        return Completion(model=model, text=self.reply)

    def embed(self, *, model: str, inputs: list[str]) -> EmbeddingResult:
        return EmbeddingResult(model=model, vectors=())
