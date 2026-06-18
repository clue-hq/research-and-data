"""Reusable contract-conformance checks (M0.6).

The fixtures every future component's tests call to assert it honours an M0 seam — most importantly
the :class:`~clue_research.core.Resolver` protocol; a new resolver (M4) proves conformance the same
way regardless of provider. These keep "replaceable without breaking neighbours" a checked property.
"""

from __future__ import annotations

from clue_research.core import Resolver, SourceManifest


def assert_resolver_conformance(candidate: object) -> None:
    """Assert ``candidate`` satisfies the ``Resolver`` protocol (a ``tier`` and a ``resolve``
    method). Raises ``AssertionError`` otherwise. Every future resolver's test suite calls this."""
    assert isinstance(candidate, Resolver), (
        f"{type(candidate).__name__} does not satisfy the Resolver protocol "
        "(needs `tier: int` and `resolve(entity, field) -> list[Claim]`)"
    )


def assert_valid_source_manifest(manifest: object) -> None:
    """Assert ``manifest`` is a well-formed :class:`~clue_research.core.SourceManifest`."""
    assert isinstance(manifest, SourceManifest), f"{manifest!r} is not a SourceManifest"
