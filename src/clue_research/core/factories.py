"""Shared claim/provenance helpers (M0.2).

The DRY constructors and primitives every component reuses instead of re-deriving:

* **provenance-enforcing constructors** — :func:`account_claim` / :func:`contact_claim`
  make the required provenance explicit in the call signature (a contact claim *cannot*
  be built without ``identity_binding`` + ``use_class``), so the invariant is visible at
  the call site as well as enforced in the model;
* **``value_json`` (de)serialization** — one round-trip path for the typed payload;
* **the trust-tier ordering helper** — the waterfall primitive (1->2->3->4, stop at the
  first confident hit). This is *not* the merge: ``current_value`` (M1) adds freshness,
  tie-breaks, and conflict detection on top.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from pydantic import JsonValue, TypeAdapter

from clue_research.core.claim import Claim, DiscoveryProvenance
from clue_research.core.enums import (
    ClaimFlavor,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    UseClass,
)
from clue_research.core.primitives import (
    Confidence,
    CostCents,
    EntityId,
    RunId,
    SourceTier,
    UtcDatetime,
)

# Resolve in this order; stop at the first source clearing the field's confidence threshold.
TIER_ORDER: tuple[int, ...] = (1, 2, 3, 4)

_VALUE_JSON: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


def to_value_json(value: object) -> JsonValue:
    """Validate/normalize a Python value into a JSON-compatible ``value_json`` payload."""
    return _VALUE_JSON.validate_python(value)


def serialize_value_json(value: object) -> str:
    """Serialize a value to a JSON string suitable for the ``value_json`` (jsonb) column."""
    return _VALUE_JSON.dump_json(to_value_json(value)).decode()


def parse_value_json(raw: str | bytes | bytearray) -> JsonValue:
    """Parse a JSON string/bytes back into a ``value_json`` payload."""
    return _VALUE_JSON.validate_json(raw)


def decode_jsonb(raw: object) -> Any:
    """Decode a value read from a *structured* jsonb column (always an object/array).

    asyncpg returns jsonb already decoded to Python objects, but a text/parameter round-trip can
    hand back a raw ``str``/``bytes``; parse only that case (``None`` passes through). The one
    decode guard every reader of an object/array jsonb column shares — e.g. ``field_definition``
    validation / tier_plan / value_schema, or ``source_profile`` weighted_sources.

    NOT for a column that may hold a bare JSON *scalar* string value (e.g. ``claim.value_json``,
    where a decoded ``"x"`` is the value, not JSON text) — use :func:`decode_jsonb_scalar` there.
    """
    if raw is None:
        return None
    return parse_value_json(raw) if isinstance(raw, (str, bytes, bytearray)) else raw


def decode_jsonb_scalar(raw: object) -> Any:
    """Decode a value read from a jsonb column that may hold a bare JSON *scalar* — e.g.
    ``claim.value_json``, where a decoded ``"robotics"`` is the value itself, not JSON text.

    The bytes-only sibling of :func:`decode_jsonb`: asyncpg returns jsonb already decoded, so a
    decoded ``str``/``int``/``dict`` passes straight through — re-parsing a decoded scalar ``str``
    would treat the value as JSON text (a bare ``"robotics"`` is not valid JSON) and reject it. Only
    a raw ``bytes``/``bytearray`` round-trip is parsed; ``None`` passes through.
    """
    if isinstance(raw, (bytes, bytearray)):
        return parse_value_json(raw)
    return raw


def parse_cost_cents(value: object) -> CostCents | None:
    """Defensively coerce an untrusted JSON-carried cost (``str``/number) to ``CostCents``.

    Returns ``None`` when the value is absent, unparseable, non-finite (``NaN``/±``Infinity``), or
    negative. ``CostCents`` is ``Annotated[Decimal, Ge(0)]``, so those values are not just invalid
    inputs — they are *dangerous* ones: a ``NaN`` signals ``InvalidOperation`` on the ordering
    comparison inside a budget check (crashing a durable phase), and a negative *inflates* remaining
    budget (a silent per-entity-cap evasion). Both a worker-supplied facet estimate and a
    client-supplied cap reach budget reservation through this one seam, so the rejection lives here
    rather than at each caller. ``is_finite()`` is checked before ``>= 0`` because a bare
    ``NaN >= 0`` comparison itself signals.
    """
    if value is None:
        return None
    try:
        cost = Decimal(str(value))
    except (ValueError, ArithmeticError):
        return None
    return cost if cost.is_finite() and cost >= 0 else None


def by_tier_ascending(claims: Iterable[Claim]) -> list[Claim]:
    """Claims ordered most-trusted first (tier 1 -> 4). Stable; does not merge."""
    return sorted(claims, key=lambda c: c.source_tier)


def first_confident_claim(claims: Iterable[Claim], min_confidence: float = 0.0) -> Claim | None:
    """The first claim (in trust order) whose confidence clears ``min_confidence``.

    The waterfall's "stop at first confident hit" (substrate §4). Returns ``None`` if no
    claim clears the threshold. This is intentionally *not* ``current_value`` (M1).
    """
    for claim in by_tier_ascending(claims):
        if claim.confidence >= min_confidence:
            return claim
    return None


def revalidate_with(claim: Claim, **updates: object) -> Claim:
    """Apply provenance ``updates`` to a frozen :class:`Claim` and **re-run validation**.

    ``model_copy(update=...)`` does not re-run validators, so a copy that changes provenance must be
    round-tripped through ``model_validate`` or an invariant could be silently bypassed. This is the
    one shared place that subtlety lives (conventions §2 / CLAUDE.md DRY): both the M4.1 waterfall
    (``_finalize`` — stamping ``source_key``/``run_id``/``research_mode``/``identity_binding``) and
    the M4.3 adapter pipeline (``_stamp_source_key``) stamp engine-owned provenance onto a
    factory-built claim through here, never re-implementing the copy-then-revalidate dance.
    """
    return Claim.model_validate(claim.model_copy(update=updates).model_dump(mode="python"))


def account_claim(
    *,
    entity_id: EntityId,
    field_key: str,
    value_json: JsonValue,
    source_tier: SourceTier,
    extraction_method: ExtractionMethod,
    confidence: Confidence,
    run_id: RunId,
    research_mode: ResearchMode,
    source_url: str | None = None,
    evidence_span: str | None = None,
    corroborations: int = 0,
    observed_at: UtcDatetime | None = None,
    cost_cents: CostCents = Decimal(0),
) -> Claim:
    """Construct an account claim (no personal-data provenance)."""
    return Claim(
        entity_id=entity_id,
        entity_type=EntityType.ACCOUNT,
        field_key=field_key,
        value_json=value_json,
        source_url=source_url,
        source_tier=source_tier,
        extraction_method=extraction_method,
        evidence_span=evidence_span,
        confidence=confidence,
        corroborations=corroborations,
        observed_at=observed_at,
        cost_cents=cost_cents,
        run_id=run_id,
        research_mode=research_mode,
    )


def contact_claim(
    *,
    entity_id: EntityId,
    field_key: str,
    value_json: JsonValue,
    source_tier: SourceTier,
    extraction_method: ExtractionMethod,
    confidence: Confidence,
    run_id: RunId,
    research_mode: ResearchMode,
    identity_binding: IdentityBinding,
    use_class: UseClass,
    source_url: str | None = None,
    evidence_span: str | None = None,
    corroborations: int = 0,
    observed_at: UtcDatetime | None = None,
    cost_cents: CostCents = Decimal(0),
) -> Claim:
    """Construct a contact claim. ``identity_binding`` and ``use_class`` are **required** —
    a personal claim carries its governance provenance from the moment it exists."""
    return Claim(
        entity_id=entity_id,
        entity_type=EntityType.CONTACT,
        field_key=field_key,
        value_json=value_json,
        source_url=source_url,
        source_tier=source_tier,
        extraction_method=extraction_method,
        evidence_span=evidence_span,
        confidence=confidence,
        corroborations=corroborations,
        observed_at=observed_at,
        cost_cents=cost_cents,
        run_id=run_id,
        research_mode=research_mode,
        identity_binding=identity_binding,
        use_class=use_class,
    )


def discovery_claim(
    *,
    entity_id: EntityId,
    entity_type: EntityType,
    field_key: str,
    value_json: JsonValue,
    source_tier: SourceTier,
    extraction_method: ExtractionMethod,
    confidence: Confidence,
    run_id: RunId,
    research_mode: ResearchMode,
    found_via: str,
    matched_signal: str,
    discovery_confidence: Confidence,
    source_url: str | None = None,
    evidence_span: str | None = None,
    corroborations: int = 0,
    observed_at: UtcDatetime | None = None,
    cost_cents: CostCents = Decimal(0),
) -> Claim:
    """Construct a **discovery-provenance** claim (modes M1/M3): records *where* an entity was found
    and *why* it matched the ICP. ``research_mode`` must be a discovery mode (the constructor builds
    a matching :class:`DiscoveryProvenance` envelope and the model enforces coherence)."""
    return Claim(
        entity_id=entity_id,
        entity_type=entity_type,
        field_key=field_key,
        value_json=value_json,
        source_url=source_url,
        source_tier=source_tier,
        extraction_method=extraction_method,
        evidence_span=evidence_span,
        confidence=confidence,
        corroborations=corroborations,
        observed_at=observed_at,
        cost_cents=cost_cents,
        run_id=run_id,
        research_mode=research_mode,
        claim_flavor=ClaimFlavor.DISCOVERY,
        discovery_provenance=DiscoveryProvenance(
            entity_id=entity_id,
            found_via=found_via,
            matched_signal=matched_signal,
            discovery_confidence=discovery_confidence,
            source_url=source_url,
            run_id=run_id,
            research_mode=research_mode,
        ),
    )


# Spec-named field-claim constructors (staged-flow §9 / §M1.4). The existing builders above *are*
# the field-claim-provenance constructors (claim_flavor defaults to FIELD_CLAIM); these aliases give
# them the names the spec uses, without a second implementation (DRY).
field_claim = account_claim
contact_field_claim = contact_claim
