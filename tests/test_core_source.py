"""M0.2 acceptance: SourceManifest round-trips all modalities and entity scopes."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clue_research.core import EntityScope, IdentityBinding, Modality, SourceManifest


@pytest.mark.parametrize("modality", list(Modality))
@pytest.mark.parametrize("scope", list(EntityScope))
def test_source_manifest_round_trips_every_modality_and_scope(
    modality: Modality, scope: EntityScope
) -> None:
    manifest = SourceManifest(
        source_key=f"src_{modality.value}_{scope.value}",
        modality=modality,
        entity_scope=scope,
        yields=("account.recent_funding", "contact.facet.recent_post"),
        tier=2,
        cost_cents=1.5,
        latency_ms=800,
        geo_coverage=("US", "EU"),
        freshness_profile="daily",
        identity_binding_strength=IdentityBinding.STRONG,
    )
    assert SourceManifest.model_validate(manifest.model_dump()) == manifest


def test_source_manifest_covers_all_five_modalities() -> None:
    assert {m.value for m in Modality} == {"text", "video", "audio", "pdf", "structured"}


def test_source_manifest_tier_is_bounded() -> None:
    with pytest.raises(ValidationError):
        SourceManifest(
            source_key="bad", modality=Modality.TEXT, entity_scope=EntityScope.BOTH, tier=5
        )


def test_yields_accepts_field_keys_and_field_classes() -> None:
    manifest = SourceManifest(
        source_key="g2",
        modality=Modality.STRUCTURED,
        entity_scope=EntityScope.ACCOUNT,
        # a full key, a resonance key, a bare class, and a pack namespace
        yields=("account.recent_funding", "account.resonance.culture", "core", "healthcare"),
        tier=3,
    )
    assert SourceManifest.model_validate(manifest.model_dump()) == manifest


@pytest.mark.parametrize("bad", ["Acme Corp", "core..x", "account.", ".core", "", "UPPER"])
def test_yields_rejects_malformed_tokens(bad: str) -> None:
    with pytest.raises(ValidationError):
        SourceManifest(
            source_key="x",
            modality=Modality.TEXT,
            entity_scope=EntityScope.BOTH,
            yields=(bad,),
            tier=1,
        )
