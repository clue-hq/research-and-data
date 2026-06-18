"""M0.4 — config-schema placeholder tests (ENG-120).

Covers the placeholder acceptance criterion of docs/specs/M00 §M0.4: typed defaults exist for
merge policy, scoring rubric, source profiles, budget caps, and freshness TTLs, and they validate
(out-of-range values raise). No engine reads these in M0 — they reserve the shared shape.

Also covers the lawful-basis-defaults + retention-TTL placeholders on the policy (Doc D §4) and
that the loader exposes the full Config with every placeholder defaulted.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from clue_research.config import (
    BudgetCaps,
    FreshnessTtls,
    JurisdictionPolicy,
    LawfulBasisDefaults,
    MergePolicy,
    RetentionTtls,
    ScoringRubric,
    SourceProfile,
    get_config,
)
from clue_research.core import CostCents


def test_all_placeholders_default_and_validate() -> None:
    """Every config-schema placeholder has typed defaults and constructs clean."""
    assert MergePolicy().conflict_tier_threshold == 2
    assert ScoringRubric().fit_weight == pytest.approx(0.5)
    assert SourceProfile().pack == "core"
    assert BudgetCaps().pass_a_cap_cents_per_account == Decimal("5")
    assert FreshnessTtls().default_ttl == timedelta(days=365)


def test_config_carries_every_placeholder_defaulted() -> None:
    cfg = get_config("acme")
    assert isinstance(cfg.merge_policy, MergePolicy)
    assert isinstance(cfg.scoring_rubric, ScoringRubric)
    assert cfg.source_profiles == ()
    assert isinstance(cfg.budget_caps, BudgetCaps)
    assert isinstance(cfg.freshness_ttls, FreshnessTtls)


def test_scoring_rubric_weights_must_sum_to_one() -> None:
    with pytest.raises(ValidationError):
        ScoringRubric(fit_weight=0.7, intent_weight=0.7)


def test_scoring_rubric_component_weights_validate() -> None:
    # valid components sum to 1.0
    ScoringRubric(fit_components={"firmographic": 0.6, "technographic": 0.4})
    with pytest.raises(ValidationError):
        ScoringRubric(fit_components={"firmographic": 0.6, "technographic": 0.6})


def test_budget_caps_reject_negative() -> None:
    with pytest.raises(ValidationError):
        BudgetCaps(per_campaign_hard_cap_cents=CostCents(Decimal("-1")))


def test_budget_caps_per_campaign_hard_cap_optional() -> None:
    """The per-campaign hard cap is None until the client confirms it (Doc C §5)."""
    assert BudgetCaps().per_campaign_hard_cap_cents is None


def test_source_profile_weight_bounds() -> None:
    with pytest.raises(ValidationError):
        SourceProfile(min_source_weight=0.8, max_source_weight=0.2)
    with pytest.raises(ValidationError):
        SourceProfile(source_weights={"exa": 1.5})


def test_merge_policy_conflict_tier_in_range() -> None:
    with pytest.raises(ValidationError):
        MergePolicy(conflict_tier_threshold=5)


def test_freshness_ttls_by_field_class_defaults() -> None:
    ttls = FreshnessTtls()
    assert ttls.by_field_class["contact.facet"] == timedelta(days=90)
    assert ttls.by_field_class["core"] == timedelta(days=365)


def test_lawful_basis_and_retention_placeholders_on_policy() -> None:
    """Lawful-basis defaults + retention TTLs are carried on the policy (Doc D §4), not enforced."""
    policy = JurisdictionPolicy()
    assert isinstance(policy.lawful_basis_defaults, LawfulBasisDefaults)
    assert policy.lawful_basis_defaults.professional_public_basis == "legitimate_interest"
    # sensitive has no default lawful basis (Art. 9 needs more than legitimate interest).
    assert policy.lawful_basis_defaults.sensitive_basis is None
    assert isinstance(policy.retention_ttls, RetentionTtls)
    # personal/sensitive claims carry SHORTER TTLs than professional facts (Doc D §4).
    assert policy.retention_ttls.sensitive_claim_ttl < policy.retention_ttls.personal_claim_ttl
    assert policy.retention_ttls.personal_claim_ttl < policy.retention_ttls.professional_claim_ttl
