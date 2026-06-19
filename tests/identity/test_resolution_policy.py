"""M2.2 — the resolution policy (policy-as-data; pure, no DB)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clue_research.identity.policy import (
    DEFAULT_RESOLUTION_POLICY,
    ResolutionPolicy,
    ScorerWeights,
)


def test_default_weights_sum_to_one_and_reserve_strong_key_budget() -> None:
    w = ScorerWeights()
    total = (
        w.name_cosine
        + w.name_token_jaccard
        + w.geo_agreement
        + w.alias_overlap
        + w.domain_agreement
        + w.registry_agreement
    )
    assert abs(total - 1.0) < 1e-6
    # The strong-key budget is the headroom a fuzzy-only match can never earn → it stays below the
    # 0.95 auto-merge band (the "never silently collapse two real companies" rule, as data).
    assert w.strong_key_budget == pytest.approx(0.15)
    assert 1.0 - w.strong_key_budget < 0.95


def test_weights_must_sum_to_one() -> None:
    with pytest.raises(ValidationError):
        ScorerWeights(name_cosine=0.9)  # others default → sum != 1.0


def test_policy_is_versioned_and_swappable() -> None:
    assert DEFAULT_RESOLUTION_POLICY.version == 1
    assert DEFAULT_RESOLUTION_POLICY.top_k == 10
    # A different version with re-weighted scorer is a pure data swap (no code change).
    tuned = ResolutionPolicy(
        version=2,
        weights=ScorerWeights(
            name_cosine=0.5,
            name_token_jaccard=0.2,
            geo_agreement=0.1,
            alias_overlap=0.05,
            domain_agreement=0.1,
            registry_agreement=0.05,
        ),
    )
    assert tuned.version == 2
    assert tuned.weights.name_cosine == 0.5


def test_policy_is_frozen() -> None:
    with pytest.raises(ValidationError):
        DEFAULT_RESOLUTION_POLICY.top_k = 99  # type: ignore[misc]
