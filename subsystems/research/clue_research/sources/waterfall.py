"""The trust-tiered waterfall engine — the executable core of the source layer (M4.1 / ENG-105).

A field is filled by walking its ``tier_plan`` in **trust-tier order** and **stopping at the first
result that clears the field's confidence threshold** (substrate §4). This is a structural bet:
the LLM (tier 4) is the *least*-trusted source, so it runs last and can never be the base a later
trustworthy source fails to overwrite. The waterfall is the **only** thing that composes resolvers;
each resolver stays uniform behind the :class:`~clue_core.Resolver` protocol and is
reached **only** through the M4.2 registry binding (``get_resolver``) — never imported here.

Guarantees:
- **stop-at-first-confident is a PRE-SPEND heuristic, not a verdict.** Clearing the threshold
  short-circuits *spend* (don't call tier 3 if tier 1 was confident); it does NOT set
  ``verification_status='verified'`` — every claim is written ``unverified`` (M9 owns the verdict).
- **tier-4 absent ⇒ correct empty, not a crash.** An unbound source (the Exa/Parallel placeholders
  until M11) yields ``stop_reason=no_resolver`` with no claims — a correct flagged-empty output.
- **conflicts are deferred to merge.** Every returned claim is written; ``current_value`` (M1.2)
  applies the tier/freshness/corroboration merge — the waterfall never resolves disagreements.
- **idempotent retry.** A step already written this ``(entity, field, tier, run_id)`` is not
  re-resolved or re-written (no double-charge / double-write); the formal key derivation is M7.4.
- **caller-driven budget.** A ``budget_envelope`` halts the walk before a step whose estimated cost
  would exceed it; enforcement policy + per-account caps are M7.5.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    BudgetTracker,
    Claim,
    ClaimId,
    ClaimTagger,
    CostCents,
    Entity,
    EntityId,
    EntityType,
    FieldDef,
    IdentityBinding,
    ResearchMode,
    RunId,
    SourceGate,
    first_confident_claim,
    revalidate_with,
)
from clue_obs.otel import (
    ATTR_COST_CENTS,
    ATTR_ENTITY_ID,
    ATTR_FIELD_KEY,
    ATTR_RESEARCH_MODE,
    ATTR_RUN_ID,
    ATTR_SOURCE_KEY,
    ATTR_SOURCE_TIER,
    apply_attributes,
    resolve_span,
    traced_step,
)
from clue_research.claimstore import PUBLIC_ONLY, WorkspaceScope, claims_for, insert_claim
from clue_research.identity import DEFAULT_REUSE_POLICY, ReusePolicy, stamp_reuse
from clue_research.sources.registry import NoResolverBoundError, get_resolver, get_source
from clue_research.sources.thresholds import DEFAULT_CONFIDENCE_THRESHOLDS, ConfidenceThresholds
from clue_storage import (
    SnapshotSink,
    StorageBackend,
    bind_snapshots,
    current_snapshot_sink,
    current_storage,
    flush_snapshots,
)


class StopReason(StrEnum):
    """Why the waterfall stopped walking a field's ``tier_plan``."""

    CONFIDENT_HIT = "confident_hit"  # a step cleared the field-class confidence threshold
    TIER_EXHAUSTED = "tier_exhausted"  # every reachable step ran; none was confident
    BUDGET_STOP = "budget_stop"  # the next step's estimated cost would exceed the envelope
    NO_RESOLVER = "no_resolver"  # nothing ran — every step was unbound/unregistered (e.g. tier-4)


class StepOutcome(StrEnum):
    """What happened at one ``tier_plan`` step."""

    RESOLVED = "resolved"  # the resolver ran and its claims were written
    NO_RESOLVER = "no_resolver"  # registered source, but no resolver bound (tier-4 placeholder)
    UNREGISTERED = "unregistered"  # source_key not in the registry at all
    INACTIVE = "inactive"  # registered but active=false → skipped
    BUDGET_SKIPPED = "budget_skipped"  # estimated cost would exceed the budget envelope
    IDEMPOTENT_SKIP = "idempotent_skip"  # already resolved this (entity, field, tier, run) → reused
    GATE_SKIPPED = "gate_skipped"  # the injected source_gate declined this source; walk continues


class TierStep(BaseModel):
    """Per-step summary — the per-source yield substrate the cost surface / learning loop read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_key: str
    tier: int | None  # the manifest tier; None when the source_key is unregistered
    outcome: StepOutcome
    n_claims: int = 0
    best_confidence: float | None = None
    confident: bool = False
    cost_cents: CostCents = Decimal(0)


class WaterfallResult(BaseModel):
    """The result of resolving one field: claim-id **references** (never blobs), the stop reason,
    the per-tier summary, and the total spend (conventions §2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: EntityId
    field_key: str
    claim_refs: tuple[ClaimId, ...] = ()
    stop_reason: StopReason
    per_tier: tuple[TierStep, ...] = ()
    total_cost_cents: CostCents = Decimal(0)

    @property
    def confident(self) -> bool:
        """Whether the field was filled by a confident hit (vs left to merge / empty)."""
        return self.stop_reason is StopReason.CONFIDENT_HIT


AttemptRecorder = Callable[[WaterfallResult], Awaitable[None]]


def _max_confidence(claims: Sequence[Claim]) -> float | None:
    return max((c.confidence for c in claims), default=None)


def _finalize(
    claim: Claim,
    *,
    source_key: str,
    expected_tier: int,
    run_id: RunId,
    mode: ResearchMode,
    identity_binding: IdentityBinding | None,
) -> Claim:
    """Stamp the engine-owned provenance the resolver cannot know — the producing ``source_key``,
    ``run_id`` and ``research_mode`` (from the run's ``mode``) — and, for a contact claim, the
    manifest's ``identity_binding_strength``. The claim's ``source_tier`` must match its
    manifest tier (a resolver lying about its tier would corrupt the merge trust order) — fail loud.
    ``model_copy`` does not re-validate, so the result is round-tripped through validation."""
    if claim.source_tier != expected_tier:
        raise ValueError(
            f"resolver for source {source_key!r} returned a claim at tier {claim.source_tier}, "
            f"but its manifest declares tier {expected_tier}; tier must match the manifest"
        )
    update: dict[str, object] = {
        "source_key": source_key,
        "run_id": run_id,
        "research_mode": mode,
    }
    if claim.entity_type is EntityType.CONTACT and identity_binding is not None:
        update["identity_binding"] = identity_binding
    # ``model_copy`` skips validators; the shared ``revalidate_with`` round-trips through validation
    # so the stamp can never silently break an invariant (conventions §2 DRY).
    return revalidate_with(claim, **update)


async def _existing_step_claims(
    conn: AsyncConnection,
    entity_id: EntityId,
    field_key: str,
    source_key: str,
    run_id: RunId,
    *,
    scope: WorkspaceScope,
) -> list[Claim]:
    """Live claims already written for this ``(entity, field, source_key, run)`` — the idempotency
    key. Keyed on ``source_key``, NOT tier: a ``tier_plan`` may list >1 source at one tier
    (``[apollo, clay]``), so tier alone would conflate them on a retry (substrate §5c). Their
    presence means a retry of this step; reuse them instead of re-resolving.

    The read is **workspace-scoped** (not ALL_WORKSPACES): idempotent reuse must never hand a caller
    back
    a *different* tenant's ``tenant_private`` claim, even though it could only carry the id (the
    read path would still filter the value out). A tenant-scoped run reuses its own public ∪ private
    claims; a public-only run reuses only public ones — so a private claim is never reused across
    the tenant boundary (substrate §2 — isolation is a data-model property, not caller-enforced)."""
    live = await claims_for(conn, entity_id, field_key, scope=scope)
    return [c for c in live if c.source_key == source_key and c.run_id == run_id]


async def resolve_field(
    conn: AsyncConnection,
    entity: Entity,
    field_def: FieldDef,
    *,
    mode: ResearchMode,
    run_id: RunId,
    workspace_id: str | None = None,
    budget_envelope: Decimal | None = None,
    cost_so_far: CostCents = Decimal(0),
    thresholds: ConfidenceThresholds = DEFAULT_CONFIDENCE_THRESHOLDS,
    reuse_policy: ReusePolicy = DEFAULT_REUSE_POLICY,
    idempotent: bool = True,
    claim_tagger: ClaimTagger | None = None,
    source_gate: SourceGate | None = None,
    attempt_recorder: AttemptRecorder | None = None,
    snapshots: SnapshotSink | None = None,
    storage: StorageBackend | None = None,
) -> WaterfallResult:
    """Fill one field by walking its ``tier_plan`` in trust order, stopping at the first confident
    hit. Writes every returned claim through M1.1 (``unverified``) and returns claim-id references.

    ``mode`` is the run's profiling research mode (M2/M4). ``budget_envelope`` is an optional
    total-spend cap (cents) honored against ``cost_so_far`` + this call's running spend.

    ``claim_tagger`` (optional) is applied to each claim after the engine's validation/provenance
    stamping and before the insert: it may re-tag the claim (e.g. the M8.4 per-claim
    ``identity_binding``/``use_class``) or return ``None`` to drop it — a dropped claim is not
    written, not surfaced, and never drives the confident-stop or the :class:`TierStep` accounting
    (both follow the *kept* set). ``source_gate`` (optional) is consulted per source before the
    resolver call (reuse and unbound sources spend nothing and are not gated); ``False`` skips that
    source (``GATE_SKIPPED``) and the walk continues. With both left ``None`` the engine behaves
    exactly as before.

    ``snapshots``/``storage`` (optional, PB-B2.3) are the shared per-run evidence-snapshot sink
    and the durable backend: captures a resolver made during ``resolve`` (the tier-2 scrape path)
    are flushed — ``artifact`` row + blob — before the step's claims are inserted, so each claim's
    ``artifact_key`` FK resolves. Left ``None`` they default to the **run-scoped ambient binding**
    (``clue_storage.bind_snapshots`` — the run owner binds a per-run, workspace-bound sink around
    the whole run; a sink must never live on a globally-registered object). The engine re-binds
    whatever it resolved around the ``resolver.resolve`` call, so the sink a resolver captures
    into is by construction the one flushed here. All ``None`` → no snapshotting, as before.

    Call inside a caller-owned transaction (``db.transaction``): claims are inserted per step, so a
    raising step rolls back cleanly and the per-run idempotency never sees a half-written step.

    **Tenant stamping (M4.5, locked decision #6).** The engine is the *only* composer, so it is the
    one place that classifies every written claim's cross-tenant ``reuse_scope`` (via
    :func:`~clue_research.identity.stamp_reuse`): public-footprint facts (firmographic /
    technographic) amortize across clients; ``crm_import`` / scoring / resonance / personal claims
    are stamped ``tenant_private`` and bound to ``workspace_id`` so client-private data never leaks
    into the shared pool (substrate §2). ``workspace_id`` is therefore **required whenever a
    resolved
    field can produce a tenant-private claim** (a CRM source, a resonance/scoring field): omitting
    it makes ``stamp_reuse`` fail loud rather than silently write it public. A public-only plan
    (the M4.1/M4.4 tier-1 enrichment path) needs no ``workspace_id``.
    """
    # Run-scoped snapshot binding (PB-B2 audit finding 5): explicit args win; otherwise pick up
    # the sink/backend the run owner bound to the call context (never a global).
    if snapshots is None:
        snapshots = current_snapshot_sink()
    if storage is None:
        storage = current_storage()
    threshold = thresholds.for_field_class(field_def.field_class)
    # The idempotency read is scoped to THIS run's tenant: a tenant run reuses its own public ∪
    # private claims; a public-only run (no tenant) reuses only public ones. This keeps a
    # tenant-private claim from ever being reused across the tenant boundary (decision #6 / §2).
    idem_scope = (
        WorkspaceScope.for_workspace(workspace_id) if workspace_id is not None else PUBLIC_ONLY
    )
    steps: list[TierStep] = []
    refs: list[ClaimId] = []
    # Seeded with the caller's prior spend so the envelope bounds (cost_so_far + this call); the
    # result's total_cost_cents is the delta (this call's spend only).
    budget = BudgetTracker(envelope_cents=budget_envelope, spent_cents=cost_so_far)
    ran_any = False
    stop_reason: StopReason | None = None

    for source_key in field_def.tier_plan:
        manifest = await get_source(conn, source_key)
        if manifest is None:
            steps.append(
                TierStep(source_key=source_key, tier=None, outcome=StepOutcome.UNREGISTERED)
            )
            continue
        tier = manifest.tier
        if not manifest.active:
            steps.append(TierStep(source_key=source_key, tier=tier, outcome=StepOutcome.INACTIVE))
            continue

        # Idempotency BEFORE the budget gate: a step already written this (entity, field, source,
        # run) is reused — that spends nothing, so it must never be blocked by the budget envelope.
        if idempotent:
            existing = await _existing_step_claims(
                conn, entity.entity_id, field_def.field_key, source_key, run_id, scope=idem_scope
            )
            if existing:
                best = first_confident_claim(existing, threshold)
                step_cost = sum((c.cost_cents for c in existing), Decimal(0))
                # Folds into the budget for *subsequent* steps, not this one.
                budget.spend(step_cost)
                refs.extend(c.id for c in existing)
                steps.append(
                    TierStep(
                        source_key=source_key,
                        tier=tier,
                        outcome=StepOutcome.IDEMPOTENT_SKIP,
                        n_claims=len(existing),
                        best_confidence=_max_confidence(existing),
                        confident=best is not None,
                        cost_cents=step_cost,
                    )
                )
                ran_any = True
                if best is not None:
                    stop_reason = StopReason.CONFIDENT_HIT
                    break
                continue

        # Budget pre-check (only for a step that will actually call a resolver): the manifest cost
        # is the pre-spend estimate (substrate §4 / D7).
        if budget.would_exceed(manifest.cost_cents):
            steps.append(
                TierStep(source_key=source_key, tier=tier, outcome=StepOutcome.BUDGET_SKIPPED)
            )
            stop_reason = StopReason.BUDGET_STOP
            break

        # Dispatch through the registry binding ONLY (the engine never imports a resolver).
        try:
            resolver = get_resolver(source_key)
        except NoResolverBoundError:
            steps.append(
                TierStep(source_key=source_key, tier=tier, outcome=StepOutcome.NO_RESOLVER)
            )
            continue

        # Per-source gate (injected seam): consulted only for a step that will actually call a
        # resolver — reuse and unbound sources spend nothing and are not gated. The gate's own
        # bookkeeping (e.g. the M9.1 gate_decision audit row) lives with the caller, not here.
        # False skips THIS source; the walk continues to the next (a higher-trust source rejected
        # is not the field's end).
        if source_gate is not None and not await source_gate(manifest.manifest):
            steps.append(
                TierStep(source_key=source_key, tier=tier, outcome=StepOutcome.GATE_SKIPPED)
            )
            continue

        with traced_step(
            resolve_span(source_key),
            **{
                ATTR_SOURCE_KEY: source_key,
                ATTR_SOURCE_TIER: tier,
                ATTR_ENTITY_ID: entity.entity_id,
                ATTR_FIELD_KEY: field_def.field_key,
                ATTR_RUN_ID: run_id,
                ATTR_RESEARCH_MODE: mode,
            },
        ) as span:
            # Re-bind the resolved sink around the resolver call: the sink the resolver captures
            # into is then, by construction, the same one flushed below — whether it arrived as
            # an explicit argument or as the run's ambient binding.
            with bind_snapshots(snapshots, storage):
                claims = list(resolver.resolve(entity, field_def))
            # Flush evidence snapshots the resolver captured (via a shared per-run SnapshotSink,
            # PB-B2.3) BEFORE the insert loop: the claims below may carry artifact_key refs, and
            # the FK requires the artifact row first. Content-addressed → idempotent, so a step
            # that captured nothing (or a re-flush) is a no-op.
            if snapshots is not None and storage is not None and snapshots.pending:
                await flush_snapshots(conn, storage, snapshots)
            kept: list[Claim] = []
            step_cost = Decimal(0)
            for c in claims:
                final = _finalize(
                    c,
                    source_key=source_key,
                    expected_tier=tier,
                    run_id=run_id,
                    mode=mode,
                    identity_binding=manifest.identity_binding_strength,
                )
                # Pre-insert tagger (injected seam): re-tag (e.g. the M8.4 per-claim binding /
                # use-class) or drop the claim. None = dropped — not inserted, not surfaced; the
                # confident-stop and the TierStep accounting below follow the KEPT set, so a
                # dropped 0.9-confidence claim never short-circuits the walk with nothing written.
                if claim_tagger is not None:
                    tagged = claim_tagger(final)
                    if tagged is None:
                        continue
                    final = tagged
                # The engine (the only composer) classifies + stamps the cross-tenant reuse scope on
                # every written claim (decision #6): a public-footprint fact drops the tenant; a
                # crm_import / scoring / resonance / personal claim is bound tenant-private. A
                # private-classifying claim with no workspace_id fails loud here (no silent leak).
                final = stamp_reuse(final, workspace_id=workspace_id, policy=reuse_policy)
                refs.append(await insert_claim(conn, final))
                kept.append(final)
                step_cost += final.cost_cents
            # A *paid* call that hard-misses (returns no claims) still cost its price — but with no
            # claim to carry it, the per-claim sum would record 0 and the spend/per-source economics
            # the source layer exists to measure would silently under-count. Fall back to the
            # manifest's per-call cost for an empty (or fully tagger-dropped) result (substrate §4 /
            # D7; M4.4 cost AC). A claim-bearing result carries that cost on its first claim.
            if not kept:
                step_cost = manifest.cost_cents
            best = first_confident_claim(kept, threshold)
            apply_attributes(
                span, {ATTR_COST_CENTS: step_cost, "best_confidence": _max_confidence(kept)}
            )

        ran_any = True
        budget.spend(step_cost)
        steps.append(
            TierStep(
                source_key=source_key,
                tier=tier,
                outcome=StepOutcome.RESOLVED,
                n_claims=len(kept),
                best_confidence=_max_confidence(kept),
                confident=best is not None,
                cost_cents=step_cost,
            )
        )
        if best is not None:
            stop_reason = StopReason.CONFIDENT_HIT
            break

    if stop_reason is None:
        # No confident hit and no budget stop. If at least one resolver ran (or was reused), the
        # tiers are genuinely exhausted; if NOTHING ran (empty plan, all inactive/unregistered, or
        # only unbound tier-4 placeholders), it is no_resolver — a correct flagged-empty output.
        stop_reason = StopReason.TIER_EXHAUSTED if ran_any else StopReason.NO_RESOLVER

    result = WaterfallResult(
        entity_id=entity.entity_id,
        field_key=field_def.field_key,
        claim_refs=tuple(refs),
        stop_reason=stop_reason,
        per_tier=tuple(steps),
        total_cost_cents=budget.spent_cents - cost_so_far,  # this call's spend only
    )
    if attempt_recorder is not None:
        await attempt_recorder(result)
    return result


async def resolve_fields(
    conn: AsyncConnection,
    entity: Entity,
    field_defs: Sequence[FieldDef],
    *,
    mode: ResearchMode,
    run_id: RunId,
    workspace_id: str | None = None,
    budget_envelope: Decimal | None = None,
    thresholds: ConfidenceThresholds = DEFAULT_CONFIDENCE_THRESHOLDS,
    reuse_policy: ReusePolicy = DEFAULT_REUSE_POLICY,
    idempotent: bool = True,
    snapshots: SnapshotSink | None = None,
    storage: StorageBackend | None = None,
    attempt_recorder: AttemptRecorder | None = None,
) -> list[WaterfallResult]:
    """Resolve several fields for one entity, threading the running spend so a single
    ``budget_envelope`` bounds the whole batch. ``workspace_id`` / ``reuse_policy`` are threaded to
    each field's tenant stamping (decision #6 — see :func:`resolve_field`); ``snapshots`` /
    ``storage`` to each field's evidence-snapshot capture+flush (explicit args win over the
    run-scoped ambient binding, exactly as in :func:`resolve_field`)."""
    results: list[WaterfallResult] = []
    spent = Decimal(0)
    for field_def in field_defs:
        result = await resolve_field(
            conn,
            entity,
            field_def,
            mode=mode,
            run_id=run_id,
            workspace_id=workspace_id,
            budget_envelope=budget_envelope,
            cost_so_far=spent,
            thresholds=thresholds,
            reuse_policy=reuse_policy,
            idempotent=idempotent,
            snapshots=snapshots,
            storage=storage,
            attempt_recorder=attempt_recorder,
        )
        results.append(result)
        spent += result.total_cost_cents
    return results
