"""Facet-aware field fill (M8.4) — the shared waterfall + injected per-claim governance.

M8.4 fills a contact's deep fields through the shared trust-tiered waterfall
(``sources.resolve_field``), which owns the walk: manifest/active checks, idempotent reuse,
provenance + tenant reuse-scope stamping, cost accounting and the confident-stop. What is M8.4's
own — the **governed** ``contact.facet.*`` layer — rides the engine's two injected seams instead of
a re-implemented walk:

- ``claim_tagger`` — computes the authoritative extraction-time per-claim ``identity_binding`` +
  ``use_class`` (born-correct, the make-or-break, staged-flow §6), overriding the coarse manifest
  prior the engine stamps; a tier-4 claim whose evidence does not bind to *this* person (the
  same-name trap) is **dropped** before the write (Decision 13) and never drives the stop.
- ``source_gate`` — the M9.1 pre-spend gate consulted per source (REJECT skips that source; the
  walk continues), so the ``gate_decision`` audit semantics stay here, never in the engine.

Resolvers for the long-tail facet sources (and the tier-4 ``exa_deep``/``parallel_task`` synthesis)
are M4/M11 and absent today, so this returns ``no_resolver`` (a correct flagged-empty output) until
they are bound at the ``api`` root.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config import DEFAULT_SOURCE_PLAN_POLICY, SourcePlanPolicy
from clue_core import (
    AccountEntity,
    Claim,
    ClaimId,
    ContactEntity,
    CostCents,
    EffectiveFieldSourcePlan,
    EntityId,
    EntityScope,
    EntityType,
    FieldDef,
    ICPSpec,
    IdentityBinding,
    PreSpendGate,
    PreSpendRequest,
    PreSpendVerdict,
    ProfileClaimView,
    ResearchMode,
    RunId,
    SourceGate,
    SourceManifest,
    SourceTier,
    revalidate_with,
)
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.profiling.contact.binding import (
    DEFAULT_BINDING_CLASSIFIER,
    BindingClassifier,
    BindingInput,
)
from clue_research.profiling.contact.use_class import DEFAULT_USE_CLASS_TAGGER, UseClassTagger
from clue_research.sources import (
    DEFAULT_CONFIDENCE_THRESHOLDS,
    ConfidenceThresholds,
    get_source,
    plan_sources,
    resolve_field,
)


@dataclass
class FacetFillResult:
    """The outcome of filling one deep contact field — references + per-claim handoff views."""

    field_key: str
    claim_refs: list[ClaimId] = dataclass_field(default_factory=list)
    profile_views: list[ProfileClaimView] = dataclass_field(default_factory=list)
    cost_cents: CostCents = Decimal(0)
    stop_reason: str = "no_resolver"


async def _planned_source_keys(
    conn: AsyncConnection,
    contact: ContactEntity,
    field_def: FieldDef,
    *,
    spec: ICPSpec | None,
    tier: str,
    plan_policy: SourcePlanPolicy,
    budget_envelope: Decimal | None,
) -> tuple[tuple[str, ...], EffectiveFieldSourcePlan | None]:
    """The ordered, modality-gated source keys to consult for this field.

    Uses the M4 Source Planner when an ICP spec is available (so the expensive-modality gate +
    source-profile ordering apply); otherwise falls back to the field's declared ``tier_plan``.
    ``plan_policy`` sets how deep the plan reaches (tier scope / deep-research preference)."""
    if spec is None:
        return field_def.tier_plan, None
    plan = await plan_sources(
        conn,
        spec=spec,
        entity=contact.as_entity(),
        field=field_def.field_key,
        mode=ResearchMode.CONTACT_PROFILING,
        tier_scope=plan_policy.effective_max_tier(),
        entity_tier=tier,
        entity_scope=EntityScope.CONTACT,
        budget_envelope=budget_envelope,
    )
    return plan.tier_plan(), getattr(plan, "effective_source_plan", None)


async def fill_contact_field(
    conn: AsyncConnection,
    contact: ContactEntity,
    account: AccountEntity,
    field_def: FieldDef,
    *,
    run_id: RunId,
    workspace_id: str,
    tier: str,
    spec: ICPSpec | None = None,
    binding_classifier: BindingClassifier = DEFAULT_BINDING_CLASSIFIER,
    use_class_tagger: UseClassTagger = DEFAULT_USE_CLASS_TAGGER,
    pre_spend_gate: PreSpendGate | None = None,
    thresholds: ConfidenceThresholds = DEFAULT_CONFIDENCE_THRESHOLDS,
    plan_policy: SourcePlanPolicy = DEFAULT_SOURCE_PLAN_POLICY,
    planning_budget_envelope: Decimal | None = None,
    required_effective_source_plan: EffectiveFieldSourcePlan | None = None,
) -> FacetFillResult:
    """Fill one deep contact field, tagging every claim's binding + use-class born-correct.

    Runs the shared waterfall over the planned sources (the planner's ordering rides the engine's
    own ``tier_plan`` seam — the aspect-worker precedent); the injected ``claim_tagger`` computes
    the per-claim ``identity_binding`` (verified-handle / co-occurrence vs name-only) and
    ``use_class`` (hint + evidence escalation) before each write, dropping a tier-4 same-name claim
    outright, and the injected ``source_gate`` consults the M9.1 pre-spend gate per source. A
    resolver-absent plan yields an empty, flagged result (correct, not a crash)."""
    plan_keys, effective_source_plan = await _planned_source_keys(
        conn,
        contact,
        field_def,
        spec=spec,
        tier=tier,
        plan_policy=plan_policy,
        budget_envelope=planning_budget_envelope,
    )
    if required_effective_source_plan is not None:
        if effective_source_plan is None:
            raise ValueError("required effective contact source plan was not compiled")
        if effective_source_plan != required_effective_source_plan:
            raise ValueError(
                f"effective source plan changed for contact field {field_def.field_key!r}"
            )
    field_for_run = field_def.model_copy(update={"tier_plan": tuple(plan_keys)})

    # The source-level binding priors the classifier reads. The engine stamps a non-None manifest
    # prior onto contact claims before the tagger runs, but the classifier must distinguish "the
    # manifest declares no prior" from the resolver's placeholder — so look the prior up per source.
    priors: dict[str, IdentityBinding | None] = {}
    for source_key in field_for_run.tier_plan:
        manifest = await get_source(conn, source_key)
        priors[source_key] = manifest.identity_binding_strength if manifest is not None else None

    def tag_claim(claim: Claim) -> Claim | None:
        binding = binding_classifier.classify(
            BindingInput(
                contact=contact,
                evidence_span=claim.evidence_span,
                source_url=claim.source_url,
                source_key=claim.source_key or "",
                manifest_prior=priors.get(claim.source_key or ""),
                account_name=account.canonical_name,
                account_aliases=account.aliases,
            )
        )
        # Target-lock (Decision 13): a tier-4 (LLM-synthesized) claim whose evidence does not
        # bind to *this* person (a name-only / same-name-stranger match) is rejected BEFORE the
        # write — the least-trusted layer must not assert an unverifiable personal fact about
        # the contact at all. A lower-tier WEAK claim is still written-but-unpromotable
        # (Decisions 7/10): it has a real source the M9 gate can re-judge, where a tier-4
        # same-name claim has only the LLM's say-so.
        if claim.source_tier >= 4 and binding is IdentityBinding.WEAK:
            return None
        use_class = use_class_tagger.tag(field_def, claim.value_json, claim.evidence_span)
        return revalidate_with(
            claim,
            identity_binding=binding,
            use_class=use_class,
        )

    source_gate: SourceGate | None = None
    if pre_spend_gate is not None:
        gate = pre_spend_gate

        async def check_source(manifest: SourceManifest) -> bool:
            # Pre-spend gate (M9.1): a facet fill is a FIELD spend — gate before the resolver call,
            # keyed on the contact + facet field at the source tier. REJECT skips this source (a
            # higher-trust one can still fill it). The gate implementation writes the
            # ``gate_decision`` audit row (AC-6) — the engine only sees the boolean.
            decision = await gate.check(
                PreSpendRequest(
                    entity_id=contact.id,
                    entity_type=EntityType.CONTACT,
                    field_key=field_def.field_key,
                    source_tier=SourceTier(manifest.tier),
                    source_key=manifest.source_key,
                    effective_source_plan=effective_source_plan,
                    run_id=run_id,
                )
            )
            return decision.verdict is not PreSpendVerdict.REJECT

        source_gate = check_source

    result = await resolve_field(
        conn,
        contact.as_entity(),
        field_for_run,
        mode=ResearchMode.CONTACT_PROFILING,
        run_id=run_id,
        workspace_id=workspace_id,
        thresholds=thresholds,
        claim_tagger=tag_claim,
        source_gate=source_gate,
        product_id=spec.product_id if spec is not None else None,
    )
    refs = list(result.claim_refs)
    return FacetFillResult(
        field_key=field_def.field_key,
        claim_refs=refs,
        profile_views=await _profile_views(
            conn,
            contact.id,
            field_def.field_key,
            refs,
            scope=WorkspaceScope.for_workspace(workspace_id),
        ),
        cost_cents=result.total_cost_cents,
        stop_reason=result.stop_reason.value,
    )


async def _profile_views(
    conn: AsyncConnection,
    entity_id: EntityId,
    field_key: str,
    refs: list[ClaimId],
    *,
    scope: WorkspaceScope,
) -> list[ProfileClaimView]:
    """Reconstruct the per-claim handoff views from the kept claim references. The engine returns
    references, never blobs (conventions §2); ``Claim.id`` is client-generated, so the written
    rows are simply re-read by id and projected — in reference order."""
    if not refs:
        return []
    by_id = {claim.id: claim for claim in await claims_for(conn, entity_id, field_key, scope=scope)}
    return [_to_view(ref, by_id[ref]) for ref in refs if ref in by_id]


def _to_view(claim_id: ClaimId, claim: Claim) -> ProfileClaimView:
    """Project a written claim to the handoff ``ProfileClaimView`` shape (M12 assembles it)."""
    return ProfileClaimView(
        claim_id=claim_id,
        value_json=claim.value_json,
        evidence_span=claim.evidence_span,
        source_tier=claim.source_tier,
        identity_binding=claim.identity_binding,
        use_class=claim.use_class,
    )
