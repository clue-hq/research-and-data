"""`profile_account` — the M8.1 account-level converge entrypoint (mode M2).

The spec names a ``profile_account(account_entity_id, icp_version, tier, run_id) ->
AccountProfileResult``
seam — the whole-account operation its acceptance criteria are written against (every deep field
filled-or-flagged, target-lock, parallel aspects, per-tier depth, idempotency). In production that
operation is realised by M7's :class:`~clue_research.durable.AccountResearchGraph` running the
field-class aspect workers (M8.1's
:class:`~clue_research.profiling.aspect_worker.AspectProfilingWorker`
+ :class:`~clue_research.profiling.resonance.ResonanceAspectWorker`). This module provides the same
operation as a **directly-callable** function for tests, non-graph callers, and the api
``DEEP``-phase
wiring — built only on the shared base + the M1–M4 services (it does **not** import ``durable``).

It mirrors the graph's lead node *without* re-using it (the independence contract forbids importing
``durable``): read the active deep account schema + ``current_value`` → compute gaps → cluster by
field-class → cap the aspect breadth at the tier's ``RecursionPolicy.max_aspect_workers`` → run one
aspect worker per cluster **in parallel** → aggregate references + coverage. The clustering rule is
a
small mirror of ``durable.planning`` (the one acknowledged DRY seam — flagged to hoist
``aspect_key_for`` into ``core.field`` so both share it).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from decimal import Decimal

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import (
    PUBLIC_ONLY,
    TenantScope,
    current_values,
    list_fields,
)
from clue_research.config import OverlayStore, RecursionPolicy
from clue_research.core import (
    AccountEntity,
    AspectContext,
    AspectWorker,
    CampaignRunId,
    ClaimId,
    CostCents,
    EntityId,
    EntityType,
    FieldClass,
    FieldDef,
    FreshnessState,
    ICPSpec,
    LLMGateway,
    PassKind,
    PreSpendGate,
    RunId,
    WorkerResult,
    WorkerStatus,
    new_campaign_run_id,
    new_run_id,
)
from clue_research.core.field import field_namespace
from clue_research.db import ConnFactory, transaction
from clue_research.identity import get_account, surviving_id
from clue_research.profiling.aspect_worker import (
    DEEP_PROFILING_PLANNER_CONFIG,
    AspectCoverage,
    AspectProfilingWorker,
    SynthesisGuard,
)
from clue_research.profiling.context import params_for_run
from clue_research.profiling.resonance import ResonanceAspectWorker
from clue_research.sources import SourcePlannerConfig

# The field-classes the account axis (M8.1/M8.2) profiles. CONTACT / CONTACT_FACET are the contact
# axis (M8.3/M8.4) and are never clustered here, so a contact field that shares an ICP is ignored.
_ACCOUNT_AXIS_CLASSES = frozenset(
    {FieldClass.CORE, FieldClass.ACCOUNT, FieldClass.ACCOUNT_RESONANCE, FieldClass.PACK}
)

# Builds the aspect worker for a field-class cluster key. The api root / a test injects one; the
# default constructs the real M8.1/M8.2 workers.
WorkerBuilder = Callable[[str], AspectWorker | None]


def aspect_key_for(field: FieldDef) -> str:
    """The aspect-cluster key for a field — its field-class, except a pack clusters by its
    namespace.

    Mirrors ``durable.planning._aspect_key`` (which M8 cannot import). DRY follow-up: hoist this to
    ``core.field`` so ``durable`` and ``profiling`` share one definition."""
    if field.field_class is FieldClass.PACK:
        return field_namespace(field.field_key)
    return field.field_class.value


def default_account_worker_builder(
    *,
    session_factory: ConnFactory = transaction,
    planner_config: SourcePlannerConfig = DEEP_PROFILING_PLANNER_CONFIG,
    gateway: LLMGateway | None = None,
    planner_model: str | None = None,
    pre_spend_gate: PreSpendGate | None = None,
    synthesis_guard: SynthesisGuard | None = None,
    config_store: OverlayStore | None = None,
) -> WorkerBuilder:
    """A :data:`WorkerBuilder` constructing the real M8.1/M8.2 workers: the resonance specialisation
    for ``account.resonance``, the generic account-profiling worker for every other account-axis
    aspect (``account`` / ``core`` / a ``<pack>`` namespace)."""

    def _build(aspect: str) -> AspectWorker:
        if aspect == FieldClass.ACCOUNT_RESONANCE.value:
            return ResonanceAspectWorker(
                session_factory=session_factory,
                planner_config=planner_config,
                gateway=gateway,
                planner_model=planner_model,
                pre_spend_gate=pre_spend_gate,
                synthesis_guard=synthesis_guard,
                config_store=config_store,
            )
        return AspectProfilingWorker(
            aspect,
            session_factory=session_factory,
            planner_config=planner_config,
            gateway=gateway,
            planner_model=planner_model,
            pre_spend_gate=pre_spend_gate,
            synthesis_guard=synthesis_guard,
            config_store=config_store,
        )

    return _build


class AccountProfileResult(BaseModel):
    """The account-level converge result (M8.1) — references + per-aspect coverage + cost, never
    claim bodies. Downstream (M9 verification, M12 handoff) reads the actual values from the claim
    store by these ids (substrate §5b)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_entity_id: EntityId
    tier: str
    run_id: RunId
    status: WorkerStatus
    aspects: tuple[AspectCoverage, ...] = ()
    claim_refs: tuple[ClaimId, ...] = ()
    cost_cents: CostCents = Decimal(0)
    # Aspects clustered out of scope by the tier's `max_aspect_workers` cap (M7.2 / Doc C §3, AC6).
    dropped_aspects: tuple[str, ...] = ()
    gap_field_count: int = 0

    @property
    def fields_targeted(self) -> int:
        return sum(a.fields_targeted for a in self.aspects)

    @property
    def fields_filled(self) -> int:
        return sum(a.fields_filled for a in self.aspects)

    @property
    def fields_empty(self) -> int:
        return sum(a.fields_empty for a in self.aspects)


async def _resolve_account(conn: AsyncConnection, entity_id: EntityId) -> AccountEntity | None:
    account = await get_account(conn, entity_id)
    if account is None:
        return None
    survivor = await surviving_id(conn, account.id, EntityType.ACCOUNT)
    if survivor != account.id:
        account = await get_account(conn, survivor)
    return account


async def _deep_account_gap_fields(
    conn: AsyncConnection, account: AccountEntity, spec: ICPSpec, *, tenant_id: str | None
) -> list[FieldDef]:
    """The deep, account-axis fields that still need research for this account (the converge gap
    set).

    Reads the registered ``pass=deep`` schema, narrows it to the ICP's active ``field_keys`` (when
    the spec declares any) and the account axis, then drops every field whose ``current_value`` is
    already  ``FRESH`` — a field with no value, or a ``STALE`` / ``EXPIRED`` one, is a gap (a refresh is
    wanted), never silently skipped (substrate §1/§6). Mirrors ``durable.planning.compute_gap_fields``
    over claimstore primitives (no ``durable`` import)."""
    deep_fields = [
        f
        for f in await list_fields(conn, pass_kind=PassKind.DEEP)
        if f.field_class in _ACCOUNT_AXIS_CLASSES
    ]
    active = set(spec.field_keys)
    if active:
        deep_fields = [f for f in deep_fields if f.field_key in active]
    if not deep_fields:
        return []

    scope = TenantScope.for_tenant(tenant_id) if tenant_id is not None else PUBLIC_ONLY
    values = await current_values(
        conn, [account.id], [f.field_key for f in deep_fields], scope=scope
    )
    gaps: list[FieldDef] = []
    for field_def in deep_fields:
        current = values.get((account.id, field_def.field_key))
        if current is None or current.freshness_state is not FreshnessState.FRESH:
            gaps.append(field_def)
    return gaps


def _cluster_by_aspect(gap_fields: Sequence[FieldDef]) -> dict[str, list[str]]:
    """Cluster gap fields into aspects by field-class (deterministic: sorted aspects, sorted
    keys)."""
    clustered: dict[str, list[str]] = {}
    for field_def in gap_fields:
        clustered.setdefault(aspect_key_for(field_def), []).append(field_def.field_key)
    return {aspect: sorted(keys) for aspect, keys in sorted(clustered.items())}


def _coverage_of(result: WorkerResult) -> AspectCoverage:
    """The aspect's coverage from its ``WorkerResult.detail`` (the real workers stamp an
    :class:`AspectCoverage` dump there); fall back to a bare summary for a worker that did not (a
    stub, or a FAILED no-worker result)."""
    try:
        return AspectCoverage.model_validate(result.detail)
    except (ValueError, TypeError):
        return AspectCoverage(
            aspect=result.aspect,
            fields_filled=len(result.claim_refs),
        )


def _rollup_status(results: Sequence[WorkerResult]) -> WorkerStatus:
    statuses = [r.status for r in results]
    if any(s is WorkerStatus.BUDGET_EXCEEDED for s in statuses):
        return WorkerStatus.BUDGET_EXCEEDED
    if statuses and all(s is WorkerStatus.FAILED for s in statuses):
        return WorkerStatus.FAILED
    if any(s in (WorkerStatus.PARTIAL, WorkerStatus.FAILED) for s in statuses):
        return WorkerStatus.PARTIAL
    return WorkerStatus.OK


async def profile_account(
    *,
    account_entity_id: EntityId,
    spec: ICPSpec,
    tier: str,
    run_id: RunId | None = None,
    campaign_run_id: CampaignRunId | None = None,
    tenant_id: str | None = None,
    budget_cap_cents: CostCents | None = None,
    session_factory: ConnFactory = transaction,
    recursion_policy: RecursionPolicy | None = None,
    worker_for: WorkerBuilder | None = None,
    gateway: LLMGateway | None = None,
    planner_model: str | None = None,
    pre_spend_gate: PreSpendGate | None = None,
    synthesis_guard: SynthesisGuard | None = None,
    config_store: OverlayStore | None = None,
) -> AccountProfileResult:
    """Profile one high-tier account: fill every deep account-axis gap field, or leave it
    empty/flagged, bounded by the tier's aspect cap and the budget envelope (M8.1).

    Returns only after every targeted field is filled or explicitly flagged, or the budget fires
    (AC1) — never silently incomplete. Aspects run **in parallel** (AC4) and return references, not
    blobs. Idempotent on ``run_id`` (the waterfall no-ops a re-run of ``(entity, field, source,
    run)`` — AC7). ``tenant_id`` defaults to ``spec.client_id`` (a campaign's tenant is its client).

    The per-aspect ``budget_envelope_cents`` is ``budget_cap_cents`` (each aspect bounded by the
    cap);
    a true cross-aspect shared budget is the M7.5 ``BudgetEngine`` (injected at the graph layer) —
    here the cap bounds each parallel aspect and the total is reported."""
    run = run_id if run_id is not None else new_run_id()
    campaign_run = campaign_run_id if campaign_run_id is not None else new_campaign_run_id()
    effective_tenant = tenant_id if tenant_id is not None else spec.client_id
    policy = recursion_policy if recursion_policy is not None else RecursionPolicy()
    build_worker = (
        worker_for
        if worker_for is not None
        else default_account_worker_builder(
            session_factory=session_factory,
            gateway=gateway,
            planner_model=planner_model,
            pre_spend_gate=pre_spend_gate,
            synthesis_guard=synthesis_guard,
            config_store=config_store,
        )
    )

    # --- plan (the lead): resolve the account, compute gaps, cluster, cap aspect breadth ---
    async with session_factory() as conn:
        account = await _resolve_account(conn, account_entity_id)
        if account is None:
            return AccountProfileResult(
                account_entity_id=account_entity_id,
                tier=tier,
                run_id=run,
                status=WorkerStatus.FAILED,
            )
        gap_fields = await _deep_account_gap_fields(conn, account, spec, tenant_id=effective_tenant)

    clusters = _cluster_by_aspect(gap_fields)
    aspect_keys = list(clusters)
    cap = policy.caps_for(tier).max_aspect_workers
    granted = aspect_keys[:cap]
    dropped = tuple(aspect_keys[cap:])

    if not granted:
        # Every deep field is already fresh (or there were none) — a complete, zero-cost converge.
        return AccountProfileResult(
            account_entity_id=account.id,
            tier=tier,
            run_id=run,
            status=WorkerStatus.OK,
            dropped_aspects=dropped,
            gap_field_count=len(gap_fields),
        )

    params = params_for_run(
        client_id=spec.client_id,
        icp_key=spec.icp_key,
        icp_version=spec.version,
        tenant_id=effective_tenant,
    )

    async def _run_aspect(aspect: str) -> WorkerResult:
        worker = build_worker(aspect)
        if worker is None:
            return WorkerResult(
                aspect=aspect,
                status=WorkerStatus.FAILED,
                detail={"reason": "no worker for aspect"},
            )
        ctx = AspectContext(
            entity_id=account.id,
            campaign_run_id=campaign_run,
            run_id=run,
            tier=tier,
            aspect=aspect,
            field_keys=tuple(clusters[aspect]),
            budget_envelope_cents=budget_cap_cents,
            params=params,
        )
        return await worker.research(ctx)

    # --- fan out: one aspect worker per cluster, in parallel (AC4) ---
    results = await asyncio.gather(*[_run_aspect(aspect) for aspect in granted])

    coverages = tuple(_coverage_of(r) for r in results)
    refs: tuple[ClaimId, ...] = tuple(ref for r in results for ref in r.claim_refs)
    cost = sum((r.cost_cents for r in results), Decimal(0))
    return AccountProfileResult(
        account_entity_id=account.id,
        tier=tier,
        run_id=run,
        status=_rollup_status(results),
        aspects=coverages,
        claim_refs=refs,
        cost_cents=cost,
        dropped_aspects=dropped,
        gap_field_count=len(gap_fields),
    )


def account_axis_workers(
    *,
    pack_namespaces: Sequence[str] = (),
    session_factory: ConnFactory = transaction,
    planner_config: SourcePlannerConfig = DEEP_PROFILING_PLANNER_CONFIG,
    gateway: LLMGateway | None = None,
    planner_model: str | None = None,
    pre_spend_gate: PreSpendGate | None = None,
    synthesis_guard: SynthesisGuard | None = None,
    config_store: OverlayStore | None = None,
) -> list[AspectWorker]:
    """The account-axis aspect workers the api composition root registers into M7's
    ``WorkerRegistry`` (the one coordination point).

    Returns one worker per account-axis aspect key the graph's field-class clustering can produce:
    the generic :class:`AspectProfilingWorker` for ``account`` / ``core`` and each enabled pack
    namespace, plus the :class:`ResonanceAspectWorker` for ``account.resonance``. ``profiling``
    cannot import ``durable`` (the independence contract), so it cannot call ``register_aspect_worker``
    itself — the api root does ``for w in account_axis_workers(...): register_aspect_worker(w)``
    after ``load_deep_profiling_pack``. ``pack_namespaces`` are the vertical packs enabled for the
    campaign (knowable at composition time); a pack aspect with no registered worker would otherwise be
    marked ``FAILED`` by the graph (``durable.graph._run_one_worker``)."""

    def _generic(aspect: str) -> AspectProfilingWorker:
        return AspectProfilingWorker(
            aspect,
            session_factory=session_factory,
            planner_config=planner_config,
            gateway=gateway,
            planner_model=planner_model,
            pre_spend_gate=pre_spend_gate,
            synthesis_guard=synthesis_guard,
            config_store=config_store,
        )

    workers: list[AspectWorker] = [
        _generic(FieldClass.CORE.value),
        _generic(FieldClass.ACCOUNT.value),
        ResonanceAspectWorker(
            session_factory=session_factory,
            planner_config=planner_config,
            gateway=gateway,
            planner_model=planner_model,
            pre_spend_gate=pre_spend_gate,
            synthesis_guard=synthesis_guard,
            config_store=config_store,
        ),
    ]
    workers.extend(_generic(ns) for ns in pack_namespaces)
    return workers


__all__ = [
    "profile_account",
    "AccountProfileResult",
    "aspect_key_for",
    "default_account_worker_builder",
    "account_axis_workers",
    "WorkerBuilder",
]
