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
    made to ``raise`` (to test sibling isolation), run a ``before`` hook (to test concurrency), or
    *request facet sub-workers* (M7.2) by emitting ``facet_requests`` on its ``WorkerResult.detail``
    — the runtime then grants/denies them through the ``SpawnGuard``. It also records the recursion
    caps the runtime handed it in ``ctx.params`` (the soft cap), and the depth it ran at."""

    def __init__(
        self,
        aspect: str,
        *,
        n_claims: int = 1,
        cost_cents: Decimal = Decimal("3"),
        events: list[str] | None = None,
        raise_exc: BaseException | None = None,
        before: Callable[[], Awaitable[None]] | None = None,
        facet_requests: list[dict[str, object]] | None = None,
    ) -> None:
        self.aspect = aspect
        self._n = n_claims
        self._cost = cost_cents
        self.events = events if events is not None else []
        self.calls = 0
        self._raise = raise_exc
        self._before = before
        self._facet_requests = facet_requests
        self.seen_params: list[dict[str, object]] = []
        self.seen_depths: list[int] = []

    async def research(self, ctx: AspectContext) -> WorkerResult:
        self.calls += 1
        self.events.append(f"work:{self.aspect}")
        self.seen_params.append(dict(ctx.params))
        self.seen_depths.append(ctx.depth)
        if self._before is not None:
            await self._before()
        if self._raise is not None:
            raise self._raise
        refs = tuple(new_claim_id() for _ in range(self._n))
        detail: dict[str, object] = {}
        if self._facet_requests is not None:
            detail["facet_requests"] = self._facet_requests
        return WorkerResult(
            aspect=self.aspect,
            status=WorkerStatus.OK,
            claim_refs=refs,
            cost_cents=self._cost,
            detail=detail,
        )


# --- in-memory fakes for the campaign-run state machine (M7.3) ---------------

from datetime import UTC, datetime  # noqa: E402
from uuid import uuid4  # noqa: E402

from clue_research.core import (  # noqa: E402
    BudgetDecision,
    BudgetScope,
    BudgetVerdict,
    BurnDown,
    CampaignPhase,
    Estimate,
    PhaseContext,
    PhaseResult,
    PhaseStatus,
)
from clue_research.durable.campaign_run import (  # noqa: E402
    AdjustmentRow,
    CampaignPhaseCheckpointRow,
    CampaignRunRow,
    TierCutoffs,
)
from clue_research.durable.enums import (  # noqa: E402
    CampaignRunStatus,
    PhaseCheckpointStatus,
)

# A fixed timestamp so the in-memory rows are deterministic (no clock dependency in pure tests).
_T0 = datetime(2026, 1, 1, tzinfo=UTC)


class FakeCampaignRunStore:
    """An in-memory :class:`~clue_research.durable.campaign.CampaignRunStore` (no DB).

    Backs the M7.3 state-machine tests so transition / pause-resume / idempotency / human-gate logic
    is exercised without Postgres. Mutable run state is kept as a dict and a fresh
    :class:`CampaignRunRow` is rebuilt on each ``get`` (mirroring the DB read). ``adjustments``
    records every journaled change so a test can assert the audit trail."""

    def __init__(self) -> None:
        self._runs: dict[CampaignRunId, dict[str, object]] = {}
        self._checkpoints: dict[
            tuple[CampaignRunId, CampaignPhase], CampaignPhaseCheckpointRow
        ] = {}
        self.adjustments: list[AdjustmentRow] = []

    async def create(
        self,
        *,
        campaign_run_id: CampaignRunId,
        client_id: str,
        icp_key: str,
        icp_version: int,
        budget_cap_cents: CostCents | None,
        tier_cutoffs: TierCutoffs,
    ) -> None:
        self._runs.setdefault(
            campaign_run_id,
            {
                "id": campaign_run_id,
                "client_id": client_id,
                "icp_key": icp_key,
                "icp_version": icp_version,
                "phase": CampaignPhase.REVERSE_PROFILING,
                "status": CampaignRunStatus.ACTIVE,
                "budget_cap_cents": budget_cap_cents,
                "spent_cents": Decimal(0),
                "tier_cutoffs": dict(tier_cutoffs),
                "paused_at": None,
                "resumed_at": None,
            },
        )

    async def get(self, campaign_run_id: CampaignRunId) -> CampaignRunRow | None:
        state = self._runs.get(campaign_run_id)
        if state is None:
            return None
        return CampaignRunRow(created_at=_T0, updated_at=_T0, **state)  # type: ignore[arg-type]

    async def transition(
        self, campaign_run_id: CampaignRunId, *, phase: CampaignPhase, status: CampaignRunStatus
    ) -> None:
        state = self._runs[campaign_run_id]
        state["phase"] = phase
        state["status"] = status

    async def mark_status(
        self,
        campaign_run_id: CampaignRunId,
        *,
        status: CampaignRunStatus,
        stamp_paused: bool = False,
        stamp_resumed: bool = False,
    ) -> None:
        state = self._runs[campaign_run_id]
        state["status"] = status
        if stamp_paused:
            state["paused_at"] = _T0
        if stamp_resumed:
            state["resumed_at"] = _T0

    async def put_checkpoint(
        self,
        *,
        campaign_run_id: CampaignRunId,
        phase: CampaignPhase,
        idempotency_key: str,
        status: PhaseCheckpointStatus,
        payload: dict[str, object],
    ) -> None:
        existing = self._checkpoints.get((campaign_run_id, phase))
        self._checkpoints[(campaign_run_id, phase)] = CampaignPhaseCheckpointRow(
            id=existing.id if existing is not None else uuid4(),
            campaign_run_id=campaign_run_id,
            phase=phase,
            idempotency_key=idempotency_key,
            status=status,
            payload=dict(payload),
            committed_at=_T0 if status is PhaseCheckpointStatus.COMMITTED else None,
            created_at=_T0,
            updated_at=_T0,
        )

    async def get_checkpoint(
        self, campaign_run_id: CampaignRunId, phase: CampaignPhase
    ) -> CampaignPhaseCheckpointRow | None:
        return self._checkpoints.get((campaign_run_id, phase))

    async def adjust(
        self,
        campaign_run_id: CampaignRunId,
        *,
        icp_version: int | None = None,
        budget_cap_cents: CostCents | None = None,
        tier_cutoffs: TierCutoffs | None = None,
    ) -> None:
        state = self._runs[campaign_run_id]
        if icp_version is not None:
            state["icp_version"] = icp_version
            self._journal(campaign_run_id, "icp_version", {"icp_version": icp_version})
        if budget_cap_cents is not None:
            state["budget_cap_cents"] = budget_cap_cents
            self._journal(
                campaign_run_id, "budget_cap", {"budget_cap_cents": str(budget_cap_cents)}
            )
        if tier_cutoffs is not None:
            state["tier_cutoffs"] = dict(tier_cutoffs)
            self._journal(campaign_run_id, "tier_cutoffs", {"tier_cutoffs": dict(tier_cutoffs)})

    def _journal(
        self, campaign_run_id: CampaignRunId, kind: str, detail: dict[str, object]
    ) -> None:
        self.adjustments.append(
            AdjustmentRow(
                id=uuid4(),
                campaign_run_id=campaign_run_id,
                kind=kind,
                detail=detail,
                created_at=_T0,
            )
        )


class RecordingPhaseHandler:
    """A recording :class:`~clue_research.core.PhaseHandler` (no IO).

    Declares the ``phase`` it serves, records each invocation and the :class:`PhaseContext` it saw,
    and returns a configurable :class:`PhaseResult` (``COMPLETED`` by default; ``PAUSED`` models the
    human ``tier_checkpoint`` gate / a budget stop; ``FAILED`` models a phase error). An optional
    ``on_run`` async hook lets a test mutate state (e.g. call ``pause``) mid-phase."""

    def __init__(
        self,
        phase: CampaignPhase,
        *,
        result_status: PhaseStatus = PhaseStatus.COMPLETED,
        payload: dict[str, object] | None = None,
        cost_cents: Decimal = Decimal(0),
        events: list[str] | None = None,
        on_run: Callable[[PhaseContext], Awaitable[None]] | None = None,
    ) -> None:
        self.phase = phase
        self._status = result_status
        self._payload = payload if payload is not None else {}
        self._cost = cost_cents
        self.calls = 0
        self.seen_contexts: list[PhaseContext] = []
        self.events = events if events is not None else []
        self._on_run = on_run

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        self.calls += 1
        self.seen_contexts.append(ctx)
        self.events.append(ctx.phase.value)
        if self._on_run is not None:
            await self._on_run(ctx)
        return PhaseResult(status=self._status, payload=dict(self._payload), cost_cents=self._cost)


class FakeBudgetEngine:
    """A minimal :class:`~clue_research.core.BudgetEngine` (M7.5 stub) for M7.3 tests.

    Only ``estimate`` (the ``pre_run_estimate`` delegate) and ``set_campaign_cap`` (the
    ``adjust(budget_cap)`` flow-through) are exercised by M7.3; ``check``/``record``/``burn_down``
    return trivially so the object still satisfies the full protocol. Records its calls for
    assertions."""

    def __init__(self, *, estimate: Estimate | None = None) -> None:
        self._estimate = estimate or Estimate(
            discovered_count=0,
            projected_deep_count=0,
            estimated_cost_cents=Decimal(0),
            cost_per_account_cents=Decimal(0),
        )
        self.caps_set: list[tuple[CampaignRunId, CostCents]] = []
        self.estimate_calls: list[dict[str, object]] = []

    async def estimate(
        self,
        campaign_run_id: CampaignRunId,
        *,
        discovered_count: int,
        tier_cutoffs: dict[str, float] | None = None,
    ) -> Estimate:
        self.estimate_calls.append(
            {"discovered_count": discovered_count, "tier_cutoffs": tier_cutoffs}
        )
        return self._estimate.model_copy(update={"discovered_count": discovered_count})

    async def check(
        self,
        *,
        scope: BudgetScope,
        projected_cents: CostCents,
        campaign_run_id: CampaignRunId,
        entity_id: EntityId | None = None,
        account_run_id: RunId | None = None,
    ) -> BudgetDecision:
        return BudgetDecision(
            verdict=BudgetVerdict.ALLOW,
            scope=scope,
            projected_cents=projected_cents,
            cap_cents=Decimal(0),
        )

    async def record(
        self,
        *,
        cost_cents: CostCents,
        scope: BudgetScope,
        campaign_run_id: CampaignRunId,
        entity_id: EntityId | None = None,
        account_run_id: RunId | None = None,
    ) -> None:
        return None

    async def set_campaign_cap(self, campaign_run_id: CampaignRunId, cap_cents: CostCents) -> None:
        self.caps_set.append((campaign_run_id, cap_cents))

    async def burn_down(self, campaign_run_id: CampaignRunId) -> BurnDown:
        zero = Decimal(0)
        return BurnDown(
            spent_cents=zero, estimated_cents=zero, cap_cents=zero, remaining_cents=zero
        )


# --- in-memory fake for the idempotency ledger (M7.4) ------------------------

from datetime import timedelta  # noqa: E402

from clue_research.core import IdempotencyScope  # noqa: E402
from clue_research.durable.enums import IdempotencyStatus  # noqa: E402
from clue_research.durable.idempotency import (  # noqa: E402
    ClaimOutcome,
    ClaimResult,
    IdempotencyLedgerRow,
)


class FakeIdempotencyStore:
    """An in-memory :class:`~clue_research.durable.idempotency.IdempotencyStore` (no DB).

    Mirrors :class:`DbIdempotencyStore`'s claim semantics so the ``idempotent`` context manager and
    the phase-machine wiring are exercised without Postgres: a fresh key (or a ``failed`` / stale /
    ``stale_after<=0`` ``in_progress`` one) is re-owned and returns ``EXECUTE``; a ``succeeded`` key
    returns ``REPLAY`` with its recorded result; a live ``in_progress`` key returns ``CONFLICT``.
    :meth:`mark_stale` simulates a crashed holder so the stale-recovery path is purely testable."""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, object]] = {}

    async def claim(
        self, *, key: str, scope: IdempotencyScope, stale_after: timedelta
    ) -> ClaimResult:
        row = self._rows.get(key)
        if row is None:
            self._rows[key] = {
                "scope": scope,
                "status": IdempotencyStatus.IN_PROGRESS,
                "result_ref": {},
                "cost_cents_charged": Decimal(0),
                "stale": False,
            }
            return ClaimResult(outcome=ClaimOutcome.EXECUTE)
        status = row["status"]
        if status is IdempotencyStatus.SUCCEEDED:
            return ClaimResult(
                outcome=ClaimOutcome.REPLAY,
                result_ref=dict(row["result_ref"]),  # type: ignore[arg-type]
                cost_cents_charged=row["cost_cents_charged"],  # type: ignore[arg-type]
            )
        if status is IdempotencyStatus.FAILED:
            row["status"] = IdempotencyStatus.IN_PROGRESS
            row["stale"] = False
            return ClaimResult(outcome=ClaimOutcome.EXECUTE)
        # in_progress: a live duplicate unless the window is zero or the holder is marked crashed.
        if stale_after <= timedelta(0) or row["stale"]:
            row["stale"] = False
            return ClaimResult(outcome=ClaimOutcome.EXECUTE)
        return ClaimResult(outcome=ClaimOutcome.CONFLICT)

    async def succeed(
        self, *, key: str, result_ref: dict[str, object], cost_cents: CostCents
    ) -> None:
        row = self._rows[key]
        row["status"] = IdempotencyStatus.SUCCEEDED
        row["result_ref"] = dict(result_ref)
        row["cost_cents_charged"] = cost_cents

    async def fail(self, *, key: str) -> None:
        row = self._rows[key]
        row["status"] = IdempotencyStatus.FAILED
        row["result_ref"] = {}
        row["cost_cents_charged"] = Decimal(0)

    async def get(self, key: str) -> IdempotencyLedgerRow | None:
        row = self._rows.get(key)
        if row is None:
            return None
        return IdempotencyLedgerRow(
            key=key,
            scope=row["scope"],  # type: ignore[arg-type]
            status=row["status"],  # type: ignore[arg-type]
            result_ref=dict(row["result_ref"]),  # type: ignore[arg-type]
            cost_cents_charged=row["cost_cents_charged"],  # type: ignore[arg-type]
            first_seen_at=_T0,
            completed_at=_T0 if row["status"] is IdempotencyStatus.SUCCEEDED else None,
            updated_at=_T0,
        )

    def mark_stale(self, key: str) -> None:
        """Simulate the in_progress holder having crashed long ago (the stale-recovery trigger)."""
        self._rows[key]["stale"] = True


# --- in-memory fake for the budget engine accounting store (M7.5) ------------

from clue_research.durable.budget import BudgetStateNotFound, BudgetStore  # noqa: E402
from clue_research.durable.budget_event import (  # noqa: E402
    AccountBudgetState,
    BudgetEventRow,
    RunBudgetState,
)
from clue_research.durable.enums import BudgetEventKind  # noqa: E402


class FakeBudgetStore:
    """An in-memory :class:`~clue_research.durable.budget.BudgetStore` (no DB).

    Backs the M7.5 budget-engine tests so estimate / check / record / set_campaign_cap / burn_down
    are exercised without Postgres. ``set_run`` / ``set_account`` seed the run/account cost state a
    test needs; ``add_spend`` / ``set_*`` mutate it exactly as :class:`DbBudgetStore` mutates the
    ``campaign_run`` / ``account_run`` columns; ``events`` records every governance event for
    assertions (the in-memory analogue of the append-only ``budget_event`` table)."""

    def __init__(self) -> None:
        self._runs: dict[CampaignRunId, dict[str, object]] = {}
        self._accounts: dict[RunId, dict[str, object]] = {}
        self.events: list[BudgetEventRow] = []
        self._seq = 0

    # -- seed helpers (test setup) --

    def set_run(
        self,
        campaign_run_id: CampaignRunId,
        *,
        spent: CostCents = Decimal(0),
        cap: CostCents | None = None,
        estimated: CostCents | None = None,
    ) -> None:
        self._runs[campaign_run_id] = {"spent": spent, "cap": cap, "estimated": estimated}

    def set_account(
        self,
        account_run_id: RunId,
        *,
        tier: str,
        cost: CostCents = Decimal(0),
        cap: CostCents | None = None,
    ) -> None:
        self._accounts[account_run_id] = {"cost": cost, "tier": tier, "cap": cap}

    # -- the BudgetStore protocol --

    async def run_state(self, campaign_run_id: CampaignRunId) -> RunBudgetState | None:
        state = self._runs.get(campaign_run_id)
        if state is None:
            return None
        return RunBudgetState(
            spent_cents=state["spent"],  # type: ignore[arg-type]
            cap_cents=state["cap"],  # type: ignore[arg-type]
            estimated_cents=state["estimated"],  # type: ignore[arg-type]
        )

    async def account_state(self, account_run_id: RunId) -> AccountBudgetState | None:
        state = self._accounts.get(account_run_id)
        if state is None:
            return None
        return AccountBudgetState(
            cost_cents=state["cost"],  # type: ignore[arg-type]
            tier=state["tier"],  # type: ignore[arg-type]
            budget_cap_cents=state["cap"],  # type: ignore[arg-type]
        )

    async def add_spend(
        self,
        *,
        campaign_run_id: CampaignRunId,
        cost_cents: CostCents,
        account_run_id: RunId | None = None,
    ) -> None:
        # Mirror DbBudgetStore.add_spend exactly: fail-loud on a missing run/account (a charge never
        # silently vanishes), and check both rows BEFORE applying either (the DB does it in one
        # transaction). No setdefault auto-create — that would diverge from production's no-op row.
        if campaign_run_id not in self._runs:
            raise BudgetStateNotFound(f"campaign_run {campaign_run_id}")
        if account_run_id is not None and account_run_id not in self._accounts:
            raise BudgetStateNotFound(f"account_run {account_run_id}")
        run = self._runs[campaign_run_id]
        run["spent"] = run["spent"] + cost_cents  # type: ignore[operator]
        if account_run_id is not None:
            acct = self._accounts[account_run_id]
            acct["cost"] = acct["cost"] + cost_cents  # type: ignore[operator]

    async def set_campaign_cap(self, campaign_run_id: CampaignRunId, cap_cents: CostCents) -> None:
        run = self._runs.setdefault(
            campaign_run_id, {"spent": Decimal(0), "cap": None, "estimated": None}
        )
        run["cap"] = cap_cents

    async def set_account_cap(self, account_run_id: RunId, cap_cents: CostCents | None) -> None:
        if account_run_id in self._accounts:
            self._accounts[account_run_id]["cap"] = cap_cents

    async def set_estimated(
        self, campaign_run_id: CampaignRunId, estimated_cents: CostCents
    ) -> None:
        run = self._runs.get(campaign_run_id)
        if (
            run is not None
        ):  # best-effort: a pre-start estimate (no run row) is a no-op, like the DB
            run["estimated"] = estimated_cents

    async def record_event(
        self,
        *,
        campaign_run_id: CampaignRunId,
        scope: BudgetScope,
        kind: BudgetEventKind,
        projected_cents: CostCents,
        cap_cents: CostCents | None,
        detail: dict[str, object] | None = None,
    ) -> None:
        self._seq += 1
        self.events.append(
            BudgetEventRow(
                id=uuid4(),
                seq=self._seq,
                campaign_run_id=campaign_run_id,
                scope=scope,
                kind=kind,
                projected_cents=projected_cents,
                cap_cents=cap_cents,
                detail=dict(detail) if detail else {},
                created_at=_T0,
            )
        )

    def kinds(self) -> list[BudgetEventKind]:
        """The recorded event kinds in order (assertion helper)."""
        return [e.kind for e in self.events]


# A static-time conformance check: the in-memory fake must satisfy the runtime-checkable protocol,
# so a test exercising the fake proves the same surface the production DbBudgetStore implements.
_FAKE_BUDGET_STORE_IS_A_STORE: type[BudgetStore] = FakeBudgetStore
