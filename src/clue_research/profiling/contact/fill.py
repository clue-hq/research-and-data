"""Facet-aware field fill (M8.4) — dispatch M4 resolvers, tag per-claim, then write.

M8.4 fills a contact's deep fields through the M4 Source Planner + resolver seam, but it cannot use
the generic waterfall (``sources.resolve_field``) for the **governed** ``contact.facet.*`` class:
the waterfall auto-inserts each claim and stamps ``identity_binding`` from the *coarse manifest
prior*, which would clobber M8.4's authoritative **per-claim** binding (the make-or-break, staged-
flow §6). So M8.4 owns this thin fill loop — it asks the planner for the ordered, modality-gated
source set, dispatches each bound resolver itself, and for every returned claim computes the
extraction-time ``identity_binding`` + ``use_class`` (born-correct) *before* the write.

Resolvers for the long-tail facet sources (and the tier-4 ``exa_deep``/``parallel_task`` synthesis)
are M4/M11 and absent today, so this returns ``no_resolver`` (a correct flagged-empty output) until
they are bound at the ``api`` root.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import TenantScope, claims_for, insert_claim
from clue_research.core import (
    AccountEntity,
    Claim,
    ClaimId,
    ContactEntity,
    CostCents,
    EntityScope,
    FieldDef,
    ICPSpec,
    IdentityBinding,
    ProfileClaimView,
    ResearchMode,
    RunId,
    revalidate_with,
)
from clue_research.identity import stamp_reuse
from clue_research.profiling.contact.binding import (
    DEFAULT_BINDING_CLASSIFIER,
    BindingClassifier,
    BindingInput,
)
from clue_research.profiling.contact.use_class import DEFAULT_USE_CLASS_TAGGER, UseClassTagger
from clue_research.sources import (
    DEFAULT_CONFIDENCE_THRESHOLDS,
    ConfidenceThresholds,
    NoResolverBoundError,
    get_resolver,
    get_source,
    plan_sources,
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
) -> tuple[str, ...]:
    """The ordered, modality-gated source keys to consult for this field.

    Uses the M4 Source Planner when an ICP spec is available (so the expensive-modality gate +
    source-profile ordering apply); otherwise falls back to the field's declared ``tier_plan``."""
    if spec is None:
        return field_def.tier_plan
    plan = await plan_sources(
        conn,
        spec=spec,
        entity=contact.as_entity(),
        field=field_def.field_key,
        mode=ResearchMode.CONTACT_PROFILING,
        entity_tier=tier,
        entity_scope=EntityScope.CONTACT,
    )
    return plan.tier_plan()


async def fill_contact_field(
    conn: AsyncConnection,
    contact: ContactEntity,
    account: AccountEntity,
    field_def: FieldDef,
    *,
    run_id: RunId,
    tenant_id: str,
    tier: str,
    spec: ICPSpec | None = None,
    binding_classifier: BindingClassifier = DEFAULT_BINDING_CLASSIFIER,
    use_class_tagger: UseClassTagger = DEFAULT_USE_CLASS_TAGGER,
    thresholds: ConfidenceThresholds = DEFAULT_CONFIDENCE_THRESHOLDS,
) -> FacetFillResult:
    """Fill one deep contact field, tagging every claim's binding + use-class born-correct.

    Walks the planned sources in trust order, dispatching each bound resolver; for each returned
    claim it computes the per-claim ``identity_binding`` (verified-handle / co-occurrence vs name-
    only) and ``use_class`` (hint + evidence escalation), target-locks to this contact, and writes
    the tenant-private claim. Stops at the first confident hit (the waterfall discipline). A
    resolver-absent plan yields an empty, flagged result (correct, not a crash)."""
    result = FacetFillResult(field_key=field_def.field_key)
    threshold = thresholds.for_field_class(field_def.field_class)
    scope = TenantScope.for_tenant(tenant_id)
    ran_any = False

    for source_key in await _planned_source_keys(conn, contact, field_def, spec=spec, tier=tier):
        try:
            resolver = get_resolver(source_key)
        except NoResolverBoundError:
            continue  # resolver absent (tier-4 synthesis / long-tail until M4/M11) → skip

        # Idempotency: reuse claims already written this (contact, field, source, run).
        existing = [
            c
            for c in await claims_for(conn, contact.id, field_def.field_key, scope=scope)
            if c.source_key == source_key and c.run_id == run_id
        ]
        if existing:
            ran_any = True
            confident = False
            for claim in existing:
                result.claim_refs.append(claim.id)
                result.profile_views.append(_to_view(claim.id, claim))
                if claim.confidence >= threshold:
                    confident = True
            if confident:
                result.stop_reason = "confident_hit"
                return result
            continue

        manifest = await get_source(conn, source_key)
        prior = manifest.identity_binding_strength if manifest is not None else None
        confident = False
        for raw in resolver.resolve(contact.as_entity(), field_def):
            binding = binding_classifier.classify(
                BindingInput(
                    contact=contact,
                    evidence_span=raw.evidence_span,
                    source_url=raw.source_url,
                    source_key=source_key,
                    manifest_prior=prior,
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
            if raw.source_tier >= 4 and binding is IdentityBinding.WEAK:
                continue
            use_class = use_class_tagger.tag(field_def, raw.value_json, raw.evidence_span)
            final = revalidate_with(
                raw,
                identity_binding=binding,
                use_class=use_class,
                run_id=run_id,
                research_mode=ResearchMode.CONTACT_PROFILING,
                source_key=source_key,
            )
            final = stamp_reuse(final, tenant_id=tenant_id)
            claim_id = await insert_claim(conn, final)
            result.claim_refs.append(claim_id)
            result.profile_views.append(_to_view(claim_id, final))
            result.cost_cents += final.cost_cents
            if final.confidence >= threshold:
                confident = True
        ran_any = True
        if confident:
            result.stop_reason = "confident_hit"
            return result

    result.stop_reason = "tier_exhausted" if ran_any else "no_resolver"
    return result


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
