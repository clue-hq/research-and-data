"""Durable-execution test harness (M7) — in-memory fakes + a migrated-DB gate.

The graph-orchestration tests run on LangGraph's in-memory saver with a fake
:class:`~clue_research.durable.graph.AccountRunStore` and recording stub workers, so the M7.1
control flow (plan-before-spawn, references-only, parallel fan-out, failing-worker isolation,
checkpoint-resume) is exercised **without** a database. The repository / enum-parity / gap-detection
tests need the real Postgres ``account_run`` table and ``pytest.skip`` when no DB is reachable,
reusing the M0.3 ``run_async`` + reachable-DB probe (DRY).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import load_core_pack
from clue_research.core import (
    AspectContext,
    CampaignRunId,
    CostCents,
    EntityId,
    RunId,
    WorkerResult,
    WorkerStatus,
    new_claim_id,
)
from clue_research.db import db_lifespan
from clue_research.durable.account_run import ReferencesIndex
from clue_research.durable.enums import AccountRunStatus
from clue_research.durable.planning import ResearchPlan

# Reuse the M0.3 single-loop coroutine runner + reachable-DB gate (DRY).
from tests.db.conftest import _db_available
from tests.db.conftest import run_async as run_async

_REPO_ROOT = Path(__file__).resolve().parents[2]


# --- DB gate (mirrors the claim-store harness) ------------------------------


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
def require_durable_db(migrated_db: bool) -> None:
    """Skip unless a migrated, reachable database (with ``account_run``) is available."""
    if not migrated_db:
        pytest.skip(
            "CLUE_DATABASE_URL unset or database unreachable; "
            "set it and run `make db-up` to exercise the durable DB tests"
        )


@asynccontextmanager
async def rollback_conn(*, seed_pack: bool = True) -> AsyncIterator[AsyncConnection]:
    """Yield a connection inside a transaction that is always rolled back (test isolation)."""
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


# --- in-memory fakes for the orchestration tests ----------------------------


class FakeAccountRunStore:
    """An in-memory :class:`~clue_research.durable.graph.AccountRunStore` (no DB).

    ``begin`` returns a canned plan and records a ``"plan"`` event; ``complete`` records the
    collected references + a ``"collect"`` event. The shared ``events`` list lets a test assert the
    plan was committed *before* any worker ran (M7.1 AC)."""

    def __init__(self, plan: ResearchPlan, *, events: list[str] | None = None) -> None:
        self._plan = plan
        self.events = events if events is not None else []
        self.begin_calls = 0
        self.completed: dict[str, object] | None = None
        self.failed_status: AccountRunStatus | None = None

    async def begin(
        self,
        *,
        account_run_id: RunId,
        campaign_run_id: CampaignRunId,
        entity_id: EntityId,
        tier: str,
        tenant_id: str | None,
        field_keys: Sequence[str] | None,
    ) -> ResearchPlan:
        self.begin_calls += 1
        self.events.append("plan")
        return self._plan

    async def complete(
        self,
        *,
        account_run_id: RunId,
        references_index: ReferencesIndex,
        cost_cents: CostCents,
        status: AccountRunStatus,
    ) -> None:
        self.events.append("collect")
        self.completed = {
            "references_index": references_index,
            "cost_cents": cost_cents,
            "status": status,
        }

    async def fail(self, *, account_run_id: RunId, status: AccountRunStatus) -> None:
        self.failed_status = status


class StubAspectWorker:
    """A recording :class:`~clue_research.core.AspectWorker` (no IO).

    Returns ``n_claims`` freshly-minted claim-id references, records each invocation, and can be
    made to ``raise`` (to test sibling isolation) or run a ``before`` hook (to test concurrency)."""

    def __init__(
        self,
        aspect: str,
        *,
        n_claims: int = 1,
        cost_cents: Decimal = Decimal("3"),
        events: list[str] | None = None,
        raise_exc: BaseException | None = None,
        before: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.aspect = aspect
        self._n = n_claims
        self._cost = cost_cents
        self.events = events if events is not None else []
        self.calls = 0
        self._raise = raise_exc
        self._before = before

    async def research(self, ctx: AspectContext) -> WorkerResult:
        self.calls += 1
        self.events.append(f"work:{self.aspect}")
        if self._before is not None:
            await self._before()
        if self._raise is not None:
            raise self._raise
        refs = tuple(new_claim_id() for _ in range(self._n))
        return WorkerResult(
            aspect=self.aspect,
            status=WorkerStatus.OK,
            claim_refs=refs,
            cost_cents=self._cost,
        )
