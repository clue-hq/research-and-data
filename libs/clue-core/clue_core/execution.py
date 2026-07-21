"""Durable-execution seams — the M7 contracts every phase/worker is wired against (Beat-0).

M7 (``durable``) is the runtime *underneath* every phase: M5/M6/M8/M9/M12 register as
:class:`PhaseHandler`\\ s into the campaign-run state machine, and M8's deep workers implement
:class:`AspectWorker`. Per the project's seam rule (conventions §2) — and exactly like the
:class:`~clue_core.resolver.Resolver` and :class:`~clue_core.gateway.LLMGateway`
protocols — the *contract* lives in ``core`` while the *implementation* lives in its package
(``durable``). That is what lets every milestone package stay import-independent of the others
(the import-linter independence contract): a handler imports ``core``, never ``durable``; the
concrete handlers are wired into the ``CampaignRun`` at the ``api`` composition root.

Beat-0 ships **only the seam** — the protocols and the frozen value types they exchange. The
``CampaignRun`` state machine, the ``AccountResearchGraph`` (LangGraph + ``AsyncPostgresSaver``),
the recursion knob, the ``BudgetEngine`` implementation, and the M7 tables are built on the M7
branch against these contracts. Workers return *references* (claim ids), never claim bodies
(substrate §5b).

Architecture sources: substrate §5 (durable execution), Doc C §4 (phases) / §5 (cost governance),
docs/specs/M07-durable-execution.md.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, JsonValue

from clue_core.claim import Claim
from clue_core.enums import (
    BudgetScope,
    BudgetVerdict,
    CampaignPhase,
    PhaseStatus,
    WorkerStatus,
)
from clue_core.field import FieldKey
from clue_core.primitives import (
    CampaignRunId,
    ClaimId,
    CostCents,
    EntityId,
    RunId,
    UnitInterval,
)
from clue_core.source import SourceManifest

# --- source-engine hooks (M4.1 ``resolve_field`` seams) ----------------------
# The waterfall engine is the only composer of resolvers; these two injectable hooks are how a
# caller layers *governance* onto the shared walk without forking it (the M8.4 contact facet fill
# is the canonical caller — its per-claim binding/use-class tagging and its M9.1 per-source
# pre-spend gating ride these seams). Like the protocols above, the *types* live in ``core`` so the
# engine (``sources``) and its callers (``profiling``) stay import-independent of each other.

# Applied to each resolver claim AFTER the engine's validation/provenance stamping and BEFORE the
# insert. Return the (re-tagged) claim to write it, or ``None`` to drop it — a dropped claim is not
# inserted, not surfaced, and never drives the confident-stop (the walk continues as if the claim
# had not been produced).
ClaimTagger = Callable[[Claim], Claim | None]

# Consulted before the engine spends on one source (after the resolver binding resolves, before
# the resolver call — an idempotent reuse or an unbound source spends nothing and is not gated).
# ``False`` skips THAT source and the walk continues; the gate's own bookkeeping (e.g. the M9.1
# ``gate_decision`` audit row) lives with the caller, never in the engine.
SourceGate = Callable[[SourceManifest], Awaitable[bool]]

# --- phase layer (M7.3: campaign-run state machine) -------------------------


class PhaseContext(BaseModel):
    """The context a phase handler receives for one phase of one campaign run (M7.3).

    Identifies the run and the active ICP version; ``params`` is the escape hatch for phase-specific
    inputs (e.g. tier cutoffs at ``SCORING``) so adding one does not force a ``core`` change. The
    handler reads claims/config it needs through the claim store and config loader — it is handed
    keys, not blobs (substrate §5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    campaign_run_id: CampaignRunId
    phase: CampaignPhase
    workspace_id: str
    icp_key: str
    icp_version: int
    budget_cap_cents: CostCents | None = None
    params: dict[str, JsonValue] = {}


class PhaseResult(BaseModel):
    """What a phase handler returns to the state machine (M7.3). ``PAUSED`` holds the run at a
    durable boundary (the human ``TIER_CHECKPOINT`` or a budget graceful-stop) without failing it;
    ``payload`` carries phase-specific output by reference (e.g. tier distribution, coverage report
    id) — never claim bodies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: PhaseStatus
    accounts_processed: int = 0
    cost_cents: CostCents = Decimal(0)
    payload: dict[str, JsonValue] = {}


@runtime_checkable
class PhaseHandler(Protocol):
    """A registered phase implementation (M5/M6/M8/M9/M12 supply these; M7.3 invokes them).

    The state machine owns ordering, checkpointing, pause/resume and idempotency; the handler owns
    only the phase's work. It declares which phase it serves so the ``CampaignRun`` can dispatch by
    ``CampaignPhase`` without importing the handler's package (``@runtime_checkable`` asserts
    ``phase`` + ``run`` are present; mypy checks the full signature)."""

    phase: CampaignPhase

    async def run(self, ctx: PhaseContext) -> PhaseResult: ...


# --- per-account graph layer (M7.1/M7.2: orchestrator + workers) ------------


class AspectContext(BaseModel):
    """The context one aspect/facet worker receives (M7.1/M7.2). The orchestrator hands the worker
    its field cluster, the sources it may use, a hard ``budget_envelope_cents`` (the M7.5 cap), and
    its recursion ``depth`` (0 = aspect, ≥1 = facet sub-worker). The worker resolves via the M4
    waterfall and writes claims to the store; it never receives or returns claim bodies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: EntityId
    campaign_run_id: CampaignRunId
    run_id: RunId  # the per-account research run (claim.run_id provenance)
    tier: str
    aspect: str
    field_keys: tuple[FieldKey, ...] = ()
    budget_envelope_cents: CostCents | None = None
    depth: int = 0
    params: dict[str, JsonValue] = {}


class WorkerResult(BaseModel):
    """What an aspect/facet worker returns to the orchestrator (M7.1) — *references only*. The
    orchestrator merges ``claim_refs`` into the account run's references index and never re-reads
    claim bodies into context. ``BUDGET_EXCEEDED`` is a governed stop, distinct from ``FAILED``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    aspect: str
    status: WorkerStatus
    claim_refs: tuple[ClaimId, ...] = ()
    cost_cents: CostCents = Decimal(0)
    detail: dict[str, JsonValue] = {}


@runtime_checkable
class AspectWorker(Protocol):
    """A worker that researches one aspect of an account (M8 implements; M7.1 spawns/bounds it).

    It declares the ``aspect`` it covers, does its IO through the M4 waterfall + the claim store,
    and returns a :class:`WorkerResult` of claim-id references plus a compact status — never blobs
    (substrate §5b). Depth and worker-count are bounded by the M7.2 recursion knob and the M7.5
    budget, enforced by the orchestrator before it spawns the worker."""

    aspect: str

    async def research(self, ctx: AspectContext) -> WorkerResult: ...


# --- cost governance (M7.5: budget engine) ----------------------------------


class Estimate(BaseModel):
    """A pre-run cost projection (M7.5) shown to the client before Pass B spend (Doc C §5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    discovered_count: int
    projected_deep_count: int
    estimated_cost_cents: CostCents
    cost_per_account_cents: CostCents
    confidence: UnitInterval = 0.5


class BudgetDecision(BaseModel):
    """The verdict of a pre-spend budget check (M7.5). ``GRACEFUL_STOP`` means a run-level cap is
    breached — finish the in-flight unit and stop at the next checkpoint, never hard-kill."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: BudgetVerdict
    scope: BudgetScope
    projected_cents: CostCents
    cap_cents: CostCents
    reason: str | None = None


class BurnDown(BaseModel):
    """Live cost accounting for a campaign run (M7.5) — the client-facing burn-down (Doc C §5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    spent_cents: CostCents
    estimated_cents: CostCents
    cap_cents: CostCents
    remaining_cents: CostCents
    per_pass_spent: dict[str, CostCents] = {}
    per_source_spent: dict[str, CostCents] = {}


@runtime_checkable
class BudgetEngine(Protocol):
    """The cost-governance seam (M7.5) — the single chokepoint for spend authorisation and
    accounting. Pass-A scoring (M6), deep workers (M8), and verification (M9) call ``check`` before
    spending and ``record`` after; the state machine (M7.3) calls ``estimate`` for the pre-run
    figure and ``burn_down`` for the live surface. The implementation (caps as versioned config,
    Postgres-backed ledger) lives on the M7 branch behind this protocol."""

    async def estimate(
        self,
        campaign_run_id: CampaignRunId,
        *,
        discovered_count: int,
        tier_cutoffs: dict[str, float] | None = None,
    ) -> Estimate: ...

    async def check(
        self,
        *,
        scope: BudgetScope,
        projected_cents: CostCents,
        campaign_run_id: CampaignRunId,
        entity_id: EntityId | None = None,
        account_run_id: RunId | None = None,
    ) -> BudgetDecision: ...

    async def record(
        self,
        *,
        cost_cents: CostCents,
        scope: BudgetScope,
        campaign_run_id: CampaignRunId,
        entity_id: EntityId | None = None,
        account_run_id: RunId | None = None,
    ) -> None: ...

    async def set_campaign_cap(
        self, campaign_run_id: CampaignRunId, cap_cents: CostCents
    ) -> None: ...

    async def burn_down(self, campaign_run_id: CampaignRunId) -> BurnDown: ...
