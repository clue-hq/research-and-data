"""M0.2 acceptance: AccountHandoff carries the four outputs' shape (overview §3)."""

from __future__ import annotations

from clue_research.core import (
    AccountHandoff,
    CommitteeMember,
    IdentityBinding,
    NarrativeSupport,
    Persona,
    ProfileClaimView,
    ProvenanceRef,
    Score,
    ScoreComponent,
    UseClass,
    ValueNarrativeItem,
    new_claim_id,
    new_entity_id,
)


def _handoff() -> AccountHandoff:
    account = new_entity_id()
    contact = new_entity_id()
    funding_claim = new_claim_id()
    hook_claim = new_claim_id()
    narrative_claim = new_claim_id()
    return AccountHandoff(
        account_entity_id=account,
        fit_score=Score(
            value=0.82,
            components=(
                ScoreComponent(
                    name="firmographic", weight=0.5, value=0.9, evidence_claim_ids=(funding_claim,)
                ),
            ),
        ),
        intent_score=Score(value=0.6),
        account_profile_claims=(
            ProfileClaimView(claim_id=funding_claim, value_json={"amount": 1}, source_tier=1),
        ),
        committee=(
            CommitteeMember(
                contact_entity_id=contact,
                persona=Persona.CHAMPION,
                role_on_committee="VP Engineering",
                profile_claims=(
                    ProfileClaimView(
                        claim_id=hook_claim,
                        value_json="spoke at KubeCon",
                        evidence_span="...spoke at KubeCon...",
                        source_tier=2,
                        identity_binding=IdentityBinding.STRONG,
                        use_class=UseClass.PROFESSIONAL_PUBLIC,
                    ),
                ),
            ),
        ),
        value_narrative=(
            ValueNarrativeItem(
                claim_id=narrative_claim,
                persona=Persona.CHAMPION,
                argument="They are scaling eng; our tooling reduces onboarding time.",
                supporting=NarrativeSupport(
                    account_evidence_ids=(funding_claim,), client_knowledge_ids=("ckb-7",)
                ),
            ),
        ),
        provenance_index={
            str(funding_claim): ProvenanceRef(
                source_url="https://example.com/funding", source_tier=1
            )
        },
    )


def test_account_handoff_has_all_overview_section3_fields() -> None:
    h = _handoff()
    # Output 1 — scores, decomposed and evidence-linked
    assert 0.0 <= h.fit_score.value <= 1.0
    assert h.fit_score.components[0].evidence_claim_ids
    assert h.intent_score.value == 0.6
    # Output 2 — account profile claims
    assert h.account_profile_claims[0].source_tier == 1
    # Output 3 — governed committee
    member = h.committee[0]
    assert member.persona is Persona.CHAMPION
    assert member.role_on_committee == "VP Engineering"
    hook = member.profile_claims[0]
    assert hook.identity_binding is IdentityBinding.STRONG
    assert hook.use_class is UseClass.PROFESSIONAL_PUBLIC
    # Output 4 — value narrative with two-sided support
    item = h.value_narrative[0]
    assert item.supporting.account_evidence_ids and item.supporting.client_knowledge_ids
    # provenance index — every fact -> its source
    assert h.provenance_index


def test_account_handoff_round_trips() -> None:
    h = _handoff()
    assert AccountHandoff.model_validate(h.model_dump()) == h
