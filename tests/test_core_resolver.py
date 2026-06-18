"""M0.2 acceptance: the Resolver protocol accepts a conformer and rejects non-conformers.

The static half (a conforming class type-checks; a class missing `tier` fails the
type-checker) is asserted inside `clue_research.core.resolver` under `TYPE_CHECKING` and is
enforced by `make typecheck`. Here we assert the runtime/structural half via the
`@runtime_checkable` protocol.
"""

from __future__ import annotations

from clue_research.core import Claim, Entity, FieldDef, Resolver


class ConformingResolver:
    tier: int = 1

    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        return []


class MissingTier:
    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        return []


class MissingResolve:
    tier: int = 1


def test_conforming_resolver_satisfies_protocol() -> None:
    resolver: Resolver = ConformingResolver()  # static conformance
    assert isinstance(resolver, Resolver)


def test_class_missing_tier_does_not_satisfy_protocol() -> None:
    assert not isinstance(MissingTier(), Resolver)


def test_class_missing_resolve_does_not_satisfy_protocol() -> None:
    assert not isinstance(MissingResolve(), Resolver)
