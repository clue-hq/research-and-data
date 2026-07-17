"""The committee existence gate — resolve a candidate person, or drop it (M8.3).

The make-or-break of mode M3 (staged-flow §6/§8): every candidate must resolve to a real canonical
contact entity *under the account* before admission. A candidate with a strong key (LinkedIn URL /
verified email) either resolves to an existing contact (reuse) or is inserted as a new contact under
the account (admit); a candidate with **no strong key has nothing to resolve to and is dropped** —
a fabricated person dies here, never acquiring discovery-provenance or downstream profiling spend.

M8 relies on the M2 deterministic contact path (strong-key exact match); the *fuzzy* contact-
matching algorithm is M2's and out of scope here (a strong-key-less name is dropped, not fuzzily
admitted). Every admitted contact resolved on a strong key, so its identity-binding is ``STRONG``
(the prior the role/persona claims carry; M8.4 computes per-claim binding for facets).
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AccountEntity,
    ClaimId,
    CostCents,
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    RunId,
    discovery_claim,
)
from clue_research.claimstore import PUBLIC_ONLY, claims_for, insert_claim
from clue_research.identity import (
    Observation,
    insert_contact_entity,
    resolve,
    surviving_id,
)
from clue_research.profiling.committee.sources import CommitteePersonCandidate

# Reuse M6's reserved discovery-only field key (a DISCOVERY-flavored claim skips field-registry
# validation, so no registration is needed): the admission evidence, not a typed field value.
DISCOVERY_PROVENANCE_FIELD = "core.discovery_provenance"


class AdmissionStatus(StrEnum):
    """The outcome of running the existence gate on one candidate."""

    ADMITTED = "admitted"  # resolved (reused) or inserted under the account; provenance written
    DROPPED = "dropped"  # no strong key — nothing to resolve to (anti-fabrication)


class AdmissionOutcome(BaseModel):
    """What admitting one candidate produced — by reference (contact id + discovery claim id)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: AdmissionStatus
    contact_entity_id: EntityId | None = None
    discovery_claim_id: ClaimId | None = None
    # The resolution-strength prior for this contact's role/persona claims. Admitted contacts
    # resolved on a strong key → STRONG (a weak/name-only candidate was dropped, not admitted).
    identity_binding: IdentityBinding = IdentityBinding.STRONG
    reused_existing: bool = False
    reason: str | None = None
    cost_cents: CostCents = Decimal(0)


async def _write_committee_provenance(
    conn: AsyncConnection,
    contact_entity_id: EntityId,
    candidate: CommitteePersonCandidate,
    *,
    run_id: RunId,
    source_tier: int,
) -> ClaimId:
    """Write (idempotently) the committee discovery-provenance claim for an admitted contact.

    Idempotent on ``(contact, run, channel)`` — a replay re-admitting the same person via the same
    source reuses the existing claim (mirrors M6's ``_existing_provenance``). Discovery provenance
    is public-footprint (a person existing at a company is a public fact; the *committee assessment*
    — role/persona — is the tenant-private part), so the idempotency read is public-scoped."""
    existing = await claims_for(
        conn, contact_entity_id, DISCOVERY_PROVENANCE_FIELD, scope=PUBLIC_ONLY
    )
    for claim in existing:
        provenance = claim.discovery_provenance
        if (
            claim.run_id == run_id
            and provenance is not None
            and provenance.found_via == candidate.source_key
        ):
            return claim.id

    # A grounding URL is required for an API/SCRAPE provenance (the candidate is grounded by
    # construction); fall back to CRM_IMPORT (no URL required) for the rare email-only candidate.
    grounding_url = candidate.source_url or candidate.linkedin_url
    method = ExtractionMethod.API if grounding_url is not None else ExtractionMethod.CRM_IMPORT
    # Discovery is admission evidence, never LLM synthesis — so a discovery claim can never be
    # tier 4 (the core.claim validator requires tier-4 ⟺ llm_synthesis). A people source is tier
    # 1-3 by nature; clamp defensively so a misconfigured tier-4 ``CommitteeSource`` degrades to
    # tier 3 instead of raising at claim construction (the LLM can never *be* the source of a
    # person — anti-fabrication).
    discovery_tier = min(source_tier, 3)

    claim = discovery_claim(
        entity_id=contact_entity_id,
        entity_type=EntityType.CONTACT,
        field_key=DISCOVERY_PROVENANCE_FIELD,
        value_json={
            "matched_channel": candidate.source_key,
            "matched_signal": candidate.matched_signal,
            "discovery_confidence": candidate.discovery_confidence,
        },
        source_tier=discovery_tier,
        extraction_method=method,
        confidence=candidate.discovery_confidence,
        run_id=run_id,
        research_mode=ResearchMode.COMMITTEE_DISCOVERY,
        found_via=candidate.source_key,
        matched_signal=candidate.matched_signal,
        discovery_confidence=candidate.discovery_confidence,
        source_url=grounding_url,
        cost_cents=candidate.cost_cents,
    )
    return await insert_claim(conn, claim)


async def admit_candidate(
    conn: AsyncConnection,
    account: AccountEntity,
    candidate: CommitteePersonCandidate,
    *,
    run_id: RunId,
    source_tier: int = 2,
) -> AdmissionOutcome:
    """Run the existence gate on one candidate: resolve (reuse) or insert under the account, then
    write discovery-provenance — or drop a strong-key-less candidate.

    The account is assumed already resolved to its survivor by the caller. Run inside the caller's
    transaction so a failure rolls back the candidate's partial writes cleanly."""
    if not candidate.has_strong_key:
        return AdmissionOutcome(
            status=AdmissionStatus.DROPPED,
            reason="no strong key (LinkedIn URL / verified email) — nothing to resolve to",
            cost_cents=candidate.cost_cents,
        )

    observation = Observation(
        entity_type=EntityType.CONTACT,
        name=candidate.full_name or "",
        linkedin_url=candidate.linkedin_url,
        verified_email=candidate.verified_email,
    )
    result = await resolve(conn, observation)

    reused = result.top is not None
    if result.top is not None:  # deterministic strong-key hit → reuse the existing contact
        contact_entity_id = await surviving_id(conn, result.top.entity_id, EntityType.CONTACT)
    else:  # strong key, but no existing contact → insert a new one under the account
        contact_entity_id = await insert_contact_entity(
            conn,
            account_entity_id=account.id,
            full_name=candidate.full_name,
            linkedin_url=candidate.linkedin_url,
            verified_email=candidate.verified_email,
            geo=candidate.geo,
        )

    discovery_claim_id = await _write_committee_provenance(
        conn, contact_entity_id, candidate, run_id=run_id, source_tier=source_tier
    )
    return AdmissionOutcome(
        status=AdmissionStatus.ADMITTED,
        contact_entity_id=contact_entity_id,
        discovery_claim_id=discovery_claim_id,
        identity_binding=IdentityBinding.STRONG,
        reused_existing=reused,
        cost_cents=candidate.cost_cents,
    )
