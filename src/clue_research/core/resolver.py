"""The ``Resolver`` protocol — the swappability seam (M0.2).

Every source — Clay, Apollo, ZoomInfo, BuiltWith, registries, CRM, Firecrawl, Exa,
Parallel — is *just a resolver* behind this one structural contract (substrate §4,
conventions §2). Nothing downstream knows a concrete provider exists, so swapping
Clay -> direct APIs is a registry/config change, not a rewrite. Implementations live in
M4's ``resolvers/<provider>/``; here we define only the protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from clue_research.core.claim import Claim
from clue_research.core.entity import Entity
from clue_research.core.field import FieldDef


class ResolverError(Exception):
    """Base of the source-layer fault taxonomy — an error raised by a :class:`Resolver`.

    Part of the protocol contract (so the durable scheduler can classify failures without importing
    a concrete resolver): everything a resolver raises derives from this. The one *meaningful*
    distinction the engine acts on is retryable-vs-not (:class:`RetryableResolverError`).
    """


class RetryableResolverError(ResolverError):
    """A **transient** provider failure (timeout, 5xx, 429 rate-limit) the engine/M7 may retry.

    The Resolver contract draws a hard line between two non-success outcomes (substrate §4 / §5;
    M4.4): a **hard miss** is an empty claim list — the field simply may end empty+flagged, a
    *correct* output the waterfall advances past; a **transient** failure raises this, so the M7
    scheduler retries rather than treating "couldn't reach the provider" as "the fact doesn't
    exist". A resolver MUST NOT fabricate a value or write a partial/guessed claim on a transient
    failure — it raises this and the step is retried (its open transaction rolls back).
    """


@runtime_checkable
class Resolver(Protocol):
    """Resolve a field for an entity into zero or more claims (substrate §4).

    A resolver returns claims carrying value, source_url, evidence_span, confidence and
    cost — it does not merge, score, or mutate the store; it only produces provenance-bearing
    claims. ``@runtime_checkable`` lets the registry assert conformance structurally at
    load time (presence of ``tier`` + ``resolve``); mypy checks the full signature.
    """

    tier: int

    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]: ...


if TYPE_CHECKING:
    # --- static conformance contract (checked by `make typecheck`, not run) ---
    # Positive: a minimal structural resolver MUST satisfy the protocol.
    class _ExampleResolver:
        tier: int = 1

        def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
            return []

    _conforms: Resolver = _ExampleResolver()

    # Negative: a class missing `tier` MUST be rejected by the type-checker. With mypy's
    # `warn_unused_ignores` (strict) this line *fails the build* unless the ignore is
    # actually triggered — i.e. it self-verifies that the protocol bites.
    class _MissingTier:
        def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
            return []

    _rejected: Resolver = _MissingTier()  # type: ignore[assignment]
