"""M0.2 acceptance: Claim construction enforces the provenance invariants, and claims are
append-only (frozen). Covers conventions §4 `claim` + the two-gates discipline."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from clue_core import (
    Claim,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    UseClass,
    VerificationStatus,
    can_be_promoted,
    new_entity_id,
    new_run_id,
)


def test_valid_account_claim_has_defaults(make_account: Callable[..., Claim]) -> None:
    claim = make_account()
    assert claim.entity_type is EntityType.ACCOUNT
    assert claim.verification_status is VerificationStatus.UNVERIFIED
    assert claim.corroborations == 0
    assert claim.collected_at.tzinfo is not None  # tz-aware
    assert claim.identity_binding is None and claim.use_class is None


@pytest.mark.parametrize("tier", [0, 5, -1, 99])
def test_source_tier_must_be_1_to_4(make_account: Callable[..., Claim], tier: int) -> None:
    with pytest.raises(ValidationError):
        make_account(source_tier=tier, extraction_method=ExtractionMethod.API)


@pytest.mark.parametrize("confidence", [-0.1, 1.1, 2.0])
def test_confidence_must_be_0_to_1(make_account: Callable[..., Claim], confidence: float) -> None:
    with pytest.raises(ValidationError):
        make_account(confidence=confidence)


def test_contact_claim_requires_identity_binding_and_use_class() -> None:
    # Missing both -> rejected (a personal claim cannot exist without its governance).
    with pytest.raises(ValidationError):
        Claim(
            entity_id=new_entity_id(),
            entity_type=EntityType.CONTACT,
            field_key="contact.facet.recent_post",
            value_json="x",
            source_tier=2,
            extraction_method=ExtractionMethod.SCRAPE,
            source_url="https://example.com",
            confidence=0.7,
            run_id=new_run_id(),
            research_mode=ResearchMode.CONTACT_PROFILING,
        )


def test_contact_claim_exposes_identity_binding_and_use_class(
    make_contact: Callable[..., Claim],
) -> None:
    claim = make_contact()
    assert claim.entity_type is EntityType.CONTACT
    assert claim.identity_binding is IdentityBinding.STRONG
    assert claim.use_class is UseClass.PROFESSIONAL_PUBLIC


def test_account_claim_does_not_require_personal_provenance(
    make_account: Callable[..., Claim],
) -> None:
    # Spec: account claims "do not require" identity_binding/use_class — they default to None.
    claim = make_account()
    assert claim.identity_binding is None
    assert claim.use_class is None
    # ...and they are not *forbidden* (we don't hardcode the deferred D3 posture in the type).
    annotated = Claim(
        entity_id=new_entity_id(),
        entity_type=EntityType.ACCOUNT,
        field_key="account.recent_funding",
        value_json={"amount": 1},
        source_tier=1,
        extraction_method=ExtractionMethod.API,
        source_url="https://example.com",
        confidence=0.9,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        identity_binding=IdentityBinding.STRONG,
        use_class=UseClass.PROFESSIONAL_PUBLIC,
    )
    assert annotated.identity_binding is IdentityBinding.STRONG


def test_tier4_and_llm_synthesis_must_agree(make_account: Callable[..., Claim]) -> None:
    # tier 4 but not synthesis
    with pytest.raises(ValidationError):
        make_account(source_tier=4, extraction_method=ExtractionMethod.API)
    # synthesis but not tier 4
    with pytest.raises(ValidationError):
        make_account(source_tier=2, extraction_method=ExtractionMethod.LLM_SYNTHESIS)


@pytest.mark.parametrize(
    "method", [ExtractionMethod.API, ExtractionMethod.SCRAPE, ExtractionMethod.LLM_SYNTHESIS]
)
def test_web_and_synthesis_methods_need_a_source_url_to_be_promotable(
    make_account: Callable[..., Claim], method: ExtractionMethod
) -> None:
    """ARV2 D1 moved this from construction to promotion: a web/synthesis claim with no
    ``source_url`` may *exist* (the lenient write gate keeps the honest observation) but stays
    ``UNVERIFIED`` forever — same shape as the span-less tier-4 rule above it."""
    tier = 4 if method is ExtractionMethod.LLM_SYNTHESIS else 2
    span = "raised $5M Series A" if method is ExtractionMethod.LLM_SYNTHESIS else None
    claim = make_account(
        extraction_method=method, source_tier=tier, source_url=None, evidence_span=span
    )
    assert claim.source_url is None
    assert can_be_promoted(claim) is False
    cited = make_account(
        extraction_method=method,
        source_tier=tier,
        source_url="https://example.com",
        evidence_span=span,
    )
    assert can_be_promoted(cited) is True


@pytest.mark.parametrize("method", [ExtractionMethod.HUMAN, ExtractionMethod.CRM_IMPORT])
def test_human_and_crm_claims_may_omit_source_url(
    make_account: Callable[..., Claim], method: ExtractionMethod
) -> None:
    claim = make_account(extraction_method=method, source_url=None)
    assert claim.source_url is None
    assert can_be_promoted(claim) is True


def test_claim_is_frozen_append_only(make_account: Callable[..., Claim]) -> None:
    claim = make_account()
    with pytest.raises(ValidationError):
        claim.confidence = 0.1  # type: ignore[misc]


def test_bad_field_key_is_rejected(make_account: Callable[..., Claim]) -> None:
    with pytest.raises(ValidationError):
        make_account(field_key="Acme Corp")  # not a namespaced key
