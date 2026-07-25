"""Pure (no-DB) tests for the M3.3 source-profile models — weight priors, validation, resolution."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clue_core import FieldClass
from clue_research.icp import (
    ResolvedSourceProfile,
    SourceWeight,
    WeightedSource,
    is_valid_source_key,
)


def test_source_weight_priors_are_ordered() -> None:
    assert SourceWeight.HIGH.prior > SourceWeight.MEDIUM.prior > SourceWeight.LOW.prior
    assert SourceWeight("high") is SourceWeight.HIGH  # StrEnum round-trips the DB/JSON value


def test_is_valid_source_key() -> None:
    assert is_valid_source_key("arxiv")
    assert is_valid_source_key("google_places")
    assert not is_valid_source_key("Glassdoor")  # uppercase
    assert not is_valid_source_key("two words")
    assert not is_valid_source_key("")


def test_weighted_source_rejects_malformed_source_key() -> None:
    with pytest.raises(ValidationError):
        WeightedSource(source_key="Bad Key", weight=SourceWeight.HIGH, rank=1)


def test_weighted_source_rejects_non_positive_rank() -> None:
    with pytest.raises(ValidationError):
        WeightedSource(source_key="arxiv", weight=SourceWeight.HIGH, rank=0)


def test_weighted_source_is_frozen() -> None:
    ws = WeightedSource(source_key="arxiv", weight=SourceWeight.HIGH, rank=1)
    with pytest.raises(ValidationError):
        ws.rank = 2  # type: ignore[misc]


def test_resolved_profile_for_field_class_falls_back_to_default() -> None:
    default = (WeightedSource(source_key="exa", weight=SourceWeight.MEDIUM, rank=1),)
    specific = (WeightedSource(source_key="arxiv", weight=SourceWeight.HIGH, rank=1),)
    profile = ResolvedSourceProfile(
        packs=("frontier_ai",),
        default=default,
        by_field_class={FieldClass.ACCOUNT_RESONANCE: specific},
    )
    # specific slot wins for its field-class
    assert profile.for_field_class(FieldClass.ACCOUNT_RESONANCE) == specific
    # any other field-class falls back to the pack-wide default
    assert profile.for_field_class(FieldClass.CORE) == default
    # pack-wide request returns the default
    assert profile.for_field_class(None) == default
