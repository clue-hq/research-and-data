"""M12.3 — per-handoff verification health (Doc C §6). Pure function, no DB.

The trust posture that travels with the served object: the tier-4 judge pass rate (over the served
value-narrative lines) and the strong-binding share (over the *unfiltered* committee, so weak claims
are in the denominator — not the post-filter handoff committee, which would read ~100%).
"""

from __future__ import annotations

from clue_core import (
    ClaimId,
    CommitteeMember,
    IdentityBinding,
    NarrativeSupport,
    Persona,
    ProfileClaimView,
    UseClass,
    ValueNarrativeItem,
    new_claim_id,
    new_entity_id,
)
from clue_research.narrative import compute_verification_health
from clue_research.narrative.handoff_seams import HandoffCommitteeMember
from clue_research.narrative.support import FaithfulnessCitation


def _narrative(persona: Persona) -> ValueNarrativeItem:
    return ValueNarrativeItem(
        claim_id=new_claim_id(),
        persona=persona,
        argument="why we matter",
        supporting=NarrativeSupport(),
    )


def _citation(claim_id: ClaimId) -> FaithfulnessCitation:
    return FaithfulnessCitation(
        claim_id=claim_id,
        verdict="supported",
        score=0.9,
        judge_model="m@1",
        answering_model="m@1",
        prompt_version="1",
    )


def _facet(binding: IdentityBinding) -> ProfileClaimView:
    return ProfileClaimView(
        claim_id=new_claim_id(),
        value_json="hook",
        source_tier=4,
        identity_binding=binding,
        use_class=UseClass.PROFESSIONAL_PUBLIC,
    )


def _member(persona: Persona, *facets: ProfileClaimView) -> HandoffCommitteeMember:
    return HandoffCommitteeMember(
        member=CommitteeMember(
            contact_entity_id=new_entity_id(),
            persona=persona,
            role_on_committee=persona.value,
            profile_claims=tuple(facets),
        )
    )


def test_health_counts_judged_and_strong_binding_shares() -> None:
    """Two narratives, one judged → 0.5 pass rate; three contact claims, two strong → 2/3 share."""
    n1, n2 = _narrative(Persona.ECONOMIC_BUYER), _narrative(Persona.TECHNICAL_EVALUATOR)
    citations = {str(n1.claim_id): _citation(n1.claim_id)}  # only n1 has a verdict
    members = (
        _member(Persona.CHAMPION, _facet(IdentityBinding.STRONG), _facet(IdentityBinding.WEAK)),
        _member(Persona.ECONOMIC_BUYER, _facet(IdentityBinding.STRONG)),
    )
    health = compute_verification_health(
        narrative=(n1, n2), citations=citations, committee_members=members
    )
    assert health.value_narrative_total == 2
    assert health.value_narrative_judged_faithful == 1
    assert health.tier4_judge_pass_rate == 0.5
    assert health.committee_contact_claims_total == 3
    assert health.committee_strong_binding == 2
    assert health.strong_binding_share == 2 / 3


def test_health_none_rates_when_denominators_zero() -> None:
    """No narrative and no identity-bound committee claim → rates are ``None`` (not a false 0.0)."""
    health = compute_verification_health(narrative=(), citations={}, committee_members=())
    assert health.value_narrative_total == 0
    assert health.tier4_judge_pass_rate is None
    assert health.strong_binding_share is None


def test_strong_binding_denominator_ignores_non_contact_claims() -> None:
    """A committee profile claim with no ``identity_binding`` (a non-contact view) is excluded from
    both numerator and denominator — only governed contact claims count."""
    non_contact = ProfileClaimView(claim_id=new_claim_id(), value_json="role", source_tier=2)
    member = HandoffCommitteeMember(
        member=CommitteeMember(
            contact_entity_id=new_entity_id(),
            persona=Persona.BLOCKER,
            role_on_committee="blocker",
            profile_claims=(non_contact, _facet(IdentityBinding.STRONG)),
        )
    )
    health = compute_verification_health(narrative=(), citations={}, committee_members=(member,))
    assert health.committee_contact_claims_total == 1  # only the bound facet
    assert health.committee_strong_binding == 1
    assert health.strong_binding_share == 1.0
