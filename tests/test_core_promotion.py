"""M0.2 acceptance: the claim-promotion predicate (substrate §1/§6, staged-flow §6)."""

from __future__ import annotations

from collections.abc import Callable

from clue_research.core import Claim, ExtractionMethod, IdentityBinding, can_be_promoted


def test_tier4_without_evidence_span_is_not_promotable(make_account: Callable[..., Claim]) -> None:
    claim = make_account(
        source_tier=4, extraction_method=ExtractionMethod.LLM_SYNTHESIS, evidence_span=None
    )
    assert can_be_promoted(claim) is False
    assert claim.is_promotable is False


def test_tier4_with_evidence_span_is_promotable(make_account: Callable[..., Claim]) -> None:
    claim = make_account(
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        evidence_span="...the company raised a Series B...",
    )
    assert can_be_promoted(claim) is True


def test_valid_corroborated_claim_is_promotable(make_account: Callable[..., Claim]) -> None:
    claim = make_account(source_tier=1, corroborations=3, confidence=0.95)
    assert can_be_promoted(claim) is True


def test_weakly_bound_contact_claim_is_not_promotable(make_contact: Callable[..., Claim]) -> None:
    claim = make_contact(identity_binding=IdentityBinding.WEAK)
    assert can_be_promoted(claim) is False


def test_strongly_bound_contact_claim_is_promotable(make_contact: Callable[..., Claim]) -> None:
    claim = make_contact(identity_binding=IdentityBinding.STRONG)
    assert can_be_promoted(claim) is True
