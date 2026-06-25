"""The mode-M2 account-profiling aspect worker (M8.1) — the converge body M7's graph spawns.

M7 (``durable``) owns the per-account orchestrator-worker graph: it computes the gap fields,
clusters
them **by field-class** into aspects (``durable/planning.build_plan`` → ``"account"`` /
``"account.resonance"`` / ``"core"`` / ``<pack>``), and dispatches one :class:`AspectWorker` per
cluster (``durable/graph._dispatch`` looks the worker up by that field-class key). M8.1 supplies the
**worker body** — :class:`AspectProfilingWorker` — that fills the cluster's ``field_keys`` it is
handed. It does *not* re-implement gap detection, scheduling, recursion, or budget accounting (all
M7); it does *not* import ``durable`` or ``verification`` (the independence contract).

The worker is mode **M2 Profiling**: *converge*, not discover (staged-flow §1/§5). For each assigned
gap field it walks a closed, target-locked fill sequence and stops — the opposite of M6's open-ended
``expand``. The whole loop terminates by construction: a finite field set, each filled by the M4
waterfall's finite ``tier_plan`` walk; the three stop states are **schema-satisfied** (a confident
hit), **sources-exhausted** (ran out of resolvers — a correct empty/flagged field), and
**budget-cap**
(the M7.5 envelope halted the walk).

The per-gap-field sequence (§C of the build contract):

1. **tenant guard** — a ``tenant_private`` field (``account.resonance.*``) with no ``tenant_id``
   is left empty/flagged rather than letting the waterfall fail loud (the params-gap fail-soft).
2. **target-lock guard** — refuse to spend open-web research on a non-lockable entity (no domain /
   registry id / name+geo); leave it empty/flagged (staged-flow §8).
3. **Source Planner** — ``plan_sources`` orders the allowed, weighted sources within tier discipline
   (skipped when no ICP spec is in context → fall back to the field's declared ``tier_plan``).
4. **pre-spend gate** (M9.1, injected; ``None`` until api-root wiring) — ``PreSpendGate.check`` with
   the first planned tier; a ``REJECT`` skips the field before any spend.
5. **waterfall** — ``resolve_field`` is the *only* composer: it walks the tier plan, writes each
   claim ``unverified`` with full provenance, stamps ``research_mode=account_profiling`` + the
   ``reuse_scope`` + the ``tenant_id``, is idempotent on ``(entity, field, source, run)``, and
   returns claim-id **references** (never blobs). M8.1 never re-inserts or re-stamps.
6. **post-fill target-lock + sensitivity validation** — a drift-prone (tier ≥ 3) claim that does not
   bind to the resolved entity, or (for resonance) a value smuggling a named individual's
   special-category attribute, is dropped from the aspect's output and counted (the M8.1 target-lock
   AC / M8.2 firewall AC).

Verification (the faithfulness judge, corroboration, the actual promotion) is the downstream M9
``VERIFICATION`` phase — M8.1 only *tags* and *invokes*, never judges its own claims.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import claims_for, get_field
from clue_research.core import (
    AccountEntity,
    AspectContext,
    Claim,
    ClaimId,
    CostCents,
    EntityType,
    FieldDef,
    GateDecision,
    ICPSpec,
    LLMGateway,
    PreSpendGate,
    PreSpendRequest,
    ResearchMode,
    RunId,
    TargetLock,
    WorkerResult,
    WorkerStatus,
)
from clue_research.core.enums import PreSpendVerdict, ReuseScope
from clue_research.core.field import resolve_reuse_scope
from clue_research.db import transaction
from clue_research.icp import get_icp_version
from clue_research.identity import get_account, surviving_id
from clue_research.profiling.context import RunContext
from clue_research.profiling.target_lock import binds_to_entity, build_target_lock, is_lockable
from clue_research.sources import (
    DEFAULT_SOURCE_PLANNER_CONFIG,
    SourcePlannerConfig,
    StopReason,
    plan_sources,
    resolve_field,
)

# The deep-profiling planner config. Identical to the M4 default except the expensive-modality
# (video/audio transcription) gate clears for **both** top-deep-tier band names. The M4 default
# gates
# expensive modalities to ``{"high"}``, but the deep tier band is named inconsistently across config
# (M6 tiering uses ``high``/``medium``; the M7 recursion knob uses ``top``/``high``), so a top-deep
# account named ``top`` would otherwise silently skip transcription. Including both names makes the
# top deep tier get the full modality set regardless of naming (``medium`` stays gated — a lower
# deep
# tier should not transcribe a 90-min podcast). Doc C §3/§7d: high tier + high-weighted source only.
DEEP_PROFILING_PLANNER_CONFIG: SourcePlannerConfig = DEFAULT_SOURCE_PLANNER_CONFIG.model_copy(
    update={"gate_expensive_entity_tiers": frozenset({"top", "high"})}
)

# A session is an async context manager yielding a connection (``db.transaction`` in production; a
# rollback-scoped connection in tests). Injected so the worker is testable without committing — the
# same DI seam M6's phase handlers use (``discovery_scoring/phases.py``).
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncConnection]]

# A per-claim screen applied post-fill: ``True`` keeps the claim, ``False`` drops it from the
# aspect's
# output (still written to the append-only store, unpromotable). M8.2's resonance firewall is one.
ClaimFilter = Callable[[Claim], bool]


class ProfilingFieldDisposition(StrEnum):
    """Why one assigned gap field ended where it did (per-field telemetry; the converge stop states
    plus the pre-spend skips). Aggregated into the worker's coverage ``detail``."""

    FILLED = "filled"  # at least one claim was written and survived validation
    SOURCES_EXHAUSTED = "sources_exhausted"  # ran (or had) no resolver that yielded — empty/flagged
    BUDGET_CAP = "budget_cap"  # the budget envelope halted the walk before this field could fill
    NOT_TARGET_LOCKABLE = "not_target_lockable"  # entity lacks a strong disambiguator — no spend
    TENANT_REQUIRED = "tenant_required"  # a tenant_private field with no tenant_id in context
    GATE_REJECTED = "gate_rejected"  # the pre-spend gate rejected the spend


@dataclass(frozen=True)
class _FieldFill:
    """Internal per-field outcome (not a contract)."""

    field_key: str
    disposition: ProfilingFieldDisposition
    refs: tuple[ClaimId, ...] = ()
    cost_cents: CostCents = Decimal(0)
    target_lock_rejected: int = 0
    filter_rejected: int = 0
    reasons: tuple[str, ...] = ()


class AspectCoverage(BaseModel):
    """The per-aspect coverage summary (Doc C §6) — references + what filled vs was left empty.

    Carried on the worker's ``WorkerResult.detail`` (so the references-only contract holds — values
    live in the claim store, this is ids + counts) and aggregated by ``profile_account`` into the
    account-level :class:`~clue_research.profiling.account.AccountProfileResult`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    aspect: str
    fields_targeted: int = 0
    fields_filled: int = 0
    fields_empty: int = 0
    target_lock_rejected: int = 0
    filter_rejected: int = 0
    # field_key -> disposition (the converge stop state per field), for the cost/observability
    # surface.
    dispositions: dict[str, str] = {}

    def as_detail(self) -> dict[str, JsonValue]:
        """The JSON-safe ``WorkerResult.detail`` payload (references stay out — ids are on
        ``claim_refs``)."""
        return self.model_dump(mode="json")


# The M11.3 pre-resolution synthesis guard (``synthesis.guard_synthesis_resolution``), injected as a
# callable so ``profiling`` need not import ``synthesis`` (the independence contract). Given a field
# + the worker's research mode it raises ``SynthesisGateError`` if an account-synthesis field is
# about to be resolved off the account axis or outside Pass B — a wiring-regression tripwire on top
# of the structural firewall (the resolver returns ``[]`` for contacts; the fields are deep-pass).
# A no-op for any non-synthesis field, so the worker may call it for every field it fills.
SynthesisGuard = Callable[[FieldDef, ResearchMode], None]


class AspectProfilingWorker:
    """A mode-M2 account-profiling :class:`~clue_research.core.AspectWorker` (M8.1).

    One instance per account aspect (field-class) the graph dispatches — ``aspect="account"`` /
    ``"core"`` / a ``<pack>`` namespace; the resonance specialisation
    (``aspect="account.resonance"``)
    is :class:`~clue_research.profiling.resonance.ResonanceAspectWorker`. Construct once with the
    injected dependencies and register it into M7's ``WorkerRegistry`` at the api root
    (``profiling/wiring.py``). Stateless across calls; the per-run context arrives in
    :class:`~clue_research.core.AspectContext`."""

    def __init__(
        self,
        aspect: str,
        *,
        session_factory: SessionFactory = transaction,
        mode: ResearchMode = ResearchMode.ACCOUNT_PROFILING,
        tier_scope: int | None = None,
        planner_config: SourcePlannerConfig = DEEP_PROFILING_PLANNER_CONFIG,
        gateway: LLMGateway | None = None,
        planner_model: str | None = None,
        pre_spend_gate: PreSpendGate | None = None,
        synthesis_guard: SynthesisGuard | None = None,
        claim_filter: ClaimFilter | None = None,
    ) -> None:
        self.aspect = aspect
        self._session_factory = session_factory
        self._mode = mode
        self._tier_scope = tier_scope
        self._planner_config = planner_config
        self._gateway = gateway
        self._planner_model = planner_model
        self._pre_spend_gate = pre_spend_gate
        self._synthesis_guard = synthesis_guard
        self._claim_filter = claim_filter

    async def research(self, ctx: AspectContext) -> WorkerResult:
        """Fill this aspect's gap ``field_keys`` for the resolved account; return references
        only."""
        rc = RunContext.from_params(ctx.params)
        async with self._session_factory() as conn:
            account = await self._resolve_account(conn, ctx)
            if account is None:
                return WorkerResult(
                    aspect=ctx.aspect,
                    status=WorkerStatus.FAILED,
                    detail={
                        "reason": "account entity not resolved",
                        "entity_id": str(ctx.entity_id),
                    },
                )
            spec = (
                await get_icp_version(conn, rc.client_id, rc.icp_key, rc.icp_version)
                if rc.has_icp
                and rc.client_id is not None
                and rc.icp_key is not None
                and rc.icp_version is not None
                else None
            )
            lock = build_target_lock(account)

            fills: list[_FieldFill] = []
            spent = Decimal(0)
            envelope = ctx.budget_envelope_cents
            for field_key in ctx.field_keys:
                field_def = await get_field(conn, field_key)
                if field_def is None:
                    fills.append(
                        _FieldFill(
                            field_key=field_key,
                            disposition=ProfilingFieldDisposition.SOURCES_EXHAUSTED,
                            reasons=("field not registered",),
                        )
                    )
                    continue
                remaining = (envelope - spent) if envelope is not None else None
                if remaining is not None and remaining <= 0:
                    # The aspect's envelope is spent — the rest of the schema halts at the cap.
                    fills.append(
                        _FieldFill(
                            field_key=field_key,
                            disposition=ProfilingFieldDisposition.BUDGET_CAP,
                        )
                    )
                    continue
                fill = await self._fill_field(
                    conn,
                    account=account,
                    field_def=field_def,
                    spec=spec,
                    lock=lock,
                    rc=rc,
                    tier=ctx.tier,
                    run_id=ctx.run_id,
                    budget_remaining=remaining,
                )
                fills.append(fill)
                spent += fill.cost_cents

        return self._assemble(ctx.aspect, fills, spent)

    # -- account resolution --

    async def _resolve_account(
        self, conn: AsyncConnection, ctx: AspectContext
    ) -> AccountEntity | None:
        """Load the resolved account, following a ``merged_into`` redirect to the survivor (M2) so
        the run profiles the canonical entity, never a merged loser."""
        account = await get_account(conn, ctx.entity_id)
        if account is None:
            return None
        survivor = await surviving_id(conn, account.id, EntityType.ACCOUNT)
        if survivor != account.id:
            account = await get_account(conn, survivor)
        return account

    # -- per-field fill --

    async def _fill_field(
        self,
        conn: AsyncConnection,
        *,
        account: AccountEntity,
        field_def: FieldDef,
        spec: ICPSpec | None,
        lock: TargetLock,
        rc: RunContext,
        tier: str,
        run_id: RunId,
        budget_remaining: CostCents | None,
    ) -> _FieldFill:
        field_key = field_def.field_key
        entity = account.as_entity()

        # 1. tenant guard: never let the waterfall fail loud on a tenant_private field with no
        # tenant.
        if resolve_reuse_scope(field_def) is ReuseScope.TENANT_PRIVATE and rc.tenant_id is None:
            return _FieldFill(
                field_key=field_key,
                disposition=ProfilingFieldDisposition.TENANT_REQUIRED,
                reasons=(
                    "tenant_private field requires a tenant_id (absent in AspectContext.params)",
                ),
            )

        # 2. target-lock guard (staged-flow §8): no open-web spend on a non-lockable entity.
        if not is_lockable(lock):
            return _FieldFill(
                field_key=field_key,
                disposition=ProfilingFieldDisposition.NOT_TARGET_LOCKABLE,
                reasons=("entity has no strong disambiguator (domain / registry id / name+geo)",),
            )

        # 3. Source Planner (skipped without an ICP spec → fall back to the field's own tier_plan).
        plan = None
        if spec is not None:
            plan = await plan_sources(
                conn,
                spec=spec,
                entity=entity,
                field=field_key,
                mode=self._mode,
                tier_scope=self._tier_scope,
                entity_tier=tier,
                budget_envelope=budget_remaining,
                gateway=self._gateway,
                planner_model=self._planner_model,
                config=self._planner_config,
            )

        # 4. pre-spend gate (M9.1; injected). Use the tier of the first source that will actually
        # RUN — not ordered_sources[0], whose modality may be gated SKIP (it would spend nothing and
        # the waterfall walks only the RUN sources via tier_plan()).
        if self._pre_spend_gate is not None and plan is not None:
            first_run = next(
                (s for s in plan.ordered_sources if s.gate_decision is GateDecision.RUN), None
            )
            if first_run is not None:
                decision = await self._pre_spend_gate.check(
                    PreSpendRequest(
                        entity_id=account.id,
                        entity_type=EntityType.ACCOUNT,
                        field_key=field_key,
                        source_tier=first_run.tier,
                        run_id=run_id,
                    )
                )
                if decision.verdict is PreSpendVerdict.REJECT:
                    return _FieldFill(
                        field_key=field_key,
                        disposition=ProfilingFieldDisposition.GATE_REJECTED,
                        reasons=decision.reasons,
                    )

        # 5. waterfall fill (the only composer: writes + stamps + reuse + idempotency).
        field_for_run = (
            field_def.model_copy(update={"tier_plan": plan.tier_plan()})
            if plan is not None
            else field_def
        )
        if not field_for_run.tier_plan:
            # Nothing to consult (empty plan / no declared sources) — a correct empty/flagged field.
            return _FieldFill(
                field_key=field_key,
                disposition=ProfilingFieldDisposition.SOURCES_EXHAUSTED,
            )
        # 4.5 synthesis guard (M11.3 defense-in-depth; injected). Asserts an account-synthesis field
        # is resolved on the account axis in Pass B before the (possibly tier-4) spend — a no-op for
        # any non-synthesis field. Raises ``SynthesisGateError`` loudly on a wiring regression.
        if self._synthesis_guard is not None:
            self._synthesis_guard(field_def, self._mode)
        result = await resolve_field(
            conn,
            entity,
            field_for_run,
            mode=self._mode,
            run_id=run_id,
            tenant_id=rc.tenant_id,
            budget_envelope=budget_remaining,
        )

        # 6. post-fill target-lock + sensitivity validation.
        refs, tl_rejected, filt_rejected = await self._validate_written(
            conn,
            account=account,
            field_key=field_key,
            run_id=run_id,
            result_refs=result.claim_refs,
            lock=lock,
            rc=rc,
        )
        disposition = self._disposition(result.stop_reason, filled=bool(refs))
        return _FieldFill(
            field_key=field_key,
            disposition=disposition,
            refs=refs,
            cost_cents=result.total_cost_cents,
            target_lock_rejected=tl_rejected,
            filter_rejected=filt_rejected,
        )

    async def _validate_written(
        self,
        conn: AsyncConnection,
        *,
        account: AccountEntity,
        field_key: str,
        run_id: RunId,
        result_refs: tuple[ClaimId, ...],
        lock: TargetLock,
        rc: RunContext,
    ) -> tuple[tuple[ClaimId, ...], int, int]:
        """Drop a written claim from the aspect's output if it fails target-lock (a drift-prone
        claim
        not bound to this entity) or the optional ``claim_filter`` (M8.2's sensitivity firewall).
        The
        claim still exists in the append-only store (unpromotable); it is simply not surfaced as
        this
        aspect's evidence. Returns ``(kept_refs, target_lock_rejected, filter_rejected)``."""
        if not result_refs:
            return (), 0, 0
        ref_set = set(result_refs)
        written = [
            c
            for c in await claims_for(conn, account.id, field_key, scope=rc.tenant_scope())
            if c.id in ref_set and c.run_id == run_id
        ]
        kept: list[ClaimId] = []
        tl_rejected = 0
        filt_rejected = 0
        for claim in written:
            if not binds_to_entity(claim, lock):
                tl_rejected += 1
                continue
            if self._claim_filter is not None and not self._claim_filter(claim):
                filt_rejected += 1
                continue
            kept.append(claim.id)
        # Preserve the waterfall's ref order for any ids we could not re-read (defensive: a value
        # filtered out of a tenant-scoped read still counts as kept by id only if it was returned).
        if not written and result_refs:
            return tuple(result_refs), 0, 0
        return tuple(kept), tl_rejected, filt_rejected

    @staticmethod
    def _disposition(stop_reason: StopReason, *, filled: bool) -> ProfilingFieldDisposition:
        if stop_reason is StopReason.BUDGET_STOP:
            return ProfilingFieldDisposition.BUDGET_CAP
        if filled:
            return ProfilingFieldDisposition.FILLED
        return ProfilingFieldDisposition.SOURCES_EXHAUSTED

    # -- assembly --

    def _assemble(self, aspect: str, fills: list[_FieldFill], cost: CostCents) -> WorkerResult:
        refs: list[ClaimId] = []
        dispositions: dict[str, str] = {}
        filled = empty = tl_rejected = filt_rejected = 0
        budget_capped = False
        for fill in fills:
            refs.extend(fill.refs)
            dispositions[fill.field_key] = fill.disposition.value
            tl_rejected += fill.target_lock_rejected
            filt_rejected += fill.filter_rejected
            if fill.disposition is ProfilingFieldDisposition.FILLED:
                filled += 1
            else:
                empty += 1
            if fill.disposition is ProfilingFieldDisposition.BUDGET_CAP:
                budget_capped = True

        coverage = AspectCoverage(
            aspect=aspect,
            fields_targeted=len(fills),
            fields_filled=filled,
            fields_empty=empty,
            target_lock_rejected=tl_rejected,
            filter_rejected=filt_rejected,
            dispositions=dispositions,
        )
        if budget_capped:
            status = WorkerStatus.BUDGET_EXCEEDED
        elif tl_rejected or filt_rejected:
            status = WorkerStatus.PARTIAL  # something was screened out — surfaced, not silent
        else:
            status = WorkerStatus.OK
        return WorkerResult(
            aspect=aspect,
            status=status,
            claim_refs=tuple(refs),
            cost_cents=cost,
            detail=coverage.as_detail(),
        )


__all__ = [
    "AspectProfilingWorker",
    "AspectCoverage",
    "ProfilingFieldDisposition",
    "SessionFactory",
    "ClaimFilter",
]
