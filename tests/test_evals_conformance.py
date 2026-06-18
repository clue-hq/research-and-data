"""M0.6 acceptance: the resolver-conformance fixture passes a valid resolver, fails a broken one."""

from __future__ import annotations

import pytest

from clue_research.core import Claim, Entity, EntityScope, FieldDef, Modality, SourceManifest
from clue_research.evals import assert_resolver_conformance, assert_valid_source_manifest


class ConformingResolver:
    tier: int = 1

    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        return []


class MissingTier:
    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        return []


class MissingResolve:
    tier: int = 1


def test_conformance_fixture_passes_a_valid_resolver() -> None:
    assert_resolver_conformance(ConformingResolver())  # does not raise


def test_conformance_fixture_fails_a_resolver_missing_tier() -> None:
    with pytest.raises(AssertionError):
        assert_resolver_conformance(MissingTier())


def test_conformance_fixture_fails_a_resolver_missing_resolve() -> None:
    with pytest.raises(AssertionError):
        assert_resolver_conformance(MissingResolve())


def test_source_manifest_conformance() -> None:
    manifest = SourceManifest(
        source_key="apollo", modality=Modality.STRUCTURED, entity_scope=EntityScope.ACCOUNT, tier=1
    )
    assert_valid_source_manifest(manifest)  # does not raise
    with pytest.raises(AssertionError):
        assert_valid_source_manifest({"not": "a manifest"})
