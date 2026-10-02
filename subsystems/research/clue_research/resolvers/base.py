"""The shared tier-1 resolver substrate — one normalizer, one backend seam (M4.4 / ENG-122).

Every deterministic provider (Clay, Apollo, ZoomInfo, BuiltWith, the registries) is the **same**
:class:`DeterministicResolver` wrapping a different :class:`EnrichmentBackend`. That split is the
whole point of the milestone:

* the **backend** holds everything provider-specific — the API call and the normalization of its
  response into provider-agnostic :class:`ResolvedField`\\s. It lives in the provider's own
  sub-package (``resolvers/<provider>/``), the only place a provider SDK may be imported
  (import-linter Rule 4); nothing it returns carries a provider-shaped type.
* the **resolver** is provider-agnostic: it asks the backend for the requested field and turns each
  :class:`ResolvedField` into a typed, tier-1 :class:`~clue_core.Claim` via the shared
  ``core.factories`` constructors (never hand-built). It knows no provider name.

Because the only thing that changes between providers is the injected backend, swapping Clay for a
direct API is binding a different backend to the same ``source_key`` — a ``tier_plan`` edit,
not a caller change (the "nothing knows Clay exists" invariant, substrate §4 / conventions
§2). The waterfall (M4.1) stamps the engine-owned provenance the resolver cannot know
(``source_key``/``run_id``/``research_mode`` and a contact claim's ``identity_binding``); the
resolver supplies only what the *source* knows — value, span, confidence, cost, use-class.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from clue_core import (
    Claim,
    Confidence,
    CostCents,
    Entity,
    EntityType,
    ExtractionMethod,
    FieldDef,
    FieldKey,
    IdentityBinding,
    ResearchMode,
    UseClass,
    account_claim,
    contact_claim,
    new_run_id,
    to_value_json,
)


class ResolvedField(BaseModel):
    """A provider's answer for one field, normalized — the only shape a backend returns.

    Carries exactly what a *source* knows: the typed value, the citing ``source_url`` (construction
    admits an ``api`` claim without one — ARV2 D1 moved the rule to ``can_be_promoted``, which
    refuses it — so this shape requires it here instead), the ``evidence_span`` (the returned
    record/field — required and non-empty so every claim is grounded, an M4.4 acceptance criterion),
    a ``confidence``, and — for a contact claim — its ``use_class``. It deliberately does **not**
    carry ``source_key``/``run_id``/``research_mode``/``identity_binding``: those are engine-owned
    provenance the waterfall stamps (adaptation/enrichment never upgrades trust).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: FieldKey
    value: JsonValue
    source_url: str = Field(min_length=1)
    evidence_span: str = Field(min_length=1)
    confidence: Confidence
    # Contact claims only (the engine does not override use_class — the source classifies it). A
    # tier-1 enrichment provider returns professional, publicly-sourced people data by default; a
    # backend may set a stricter class. Ignored when the resolved entity is an account.
    use_class: UseClass = UseClass.PROFESSIONAL_PUBLIC


def resolved_field(
    field_key: str,
    value: JsonValue,
    *,
    source_url: str,
    confidence: float,
    use_class: UseClass = UseClass.PROFESSIONAL_PUBLIC,
) -> ResolvedField:
    """Build a :class:`ResolvedField` with a grounding ``evidence_span`` derived from the value.

    The shared constructor every provider ``normalize`` uses so the grounding span is built one way
    (DRY): a structured API claim's evidence *is* the returned field=value pair (the spec's
    "evidence_span = the returned record/field"), cited by ``source_url``. Keeps the span non-empty
    and provider-neutral (it names the field and value, not the provider — the no-leak invariant).
    """
    return ResolvedField(
        field_key=field_key,
        value=value,
        source_url=source_url,
        evidence_span=f"{field_key}={value!r}",
        confidence=confidence,
        use_class=use_class,
    )


def normalize_record(
    payload: Mapping[str, Any],
    field: FieldDef,
    *,
    field_map: Mapping[str, str],
    url_key: str,
    url_base: str,
    confidence_key: str,
    default_confidence: float,
    use_class: UseClass = UseClass.PROFESSIONAL_PUBLIC,
) -> list[ResolvedField]:
    """Normalize one flat enrichment record into the requested field's :class:`ResolvedField`.

    The shared shape of every structured-DB enrichment provider (Clay/Apollo/ZoomInfo/BuiltWith):
    look up the requested ``field`` in this provider's ``field_map`` (our key → the provider's
    response key), read that value, and ground it. ``field`` not in the map, or the value missing/
    empty, is a *hard miss* → ``[]`` (the field may end empty+flagged, never fabricated). Each
    provider keeps its own ``normalize`` symbol (a thin wrapper) so its mapping is testable in
    isolation, while the extraction/grounding logic lives once here (conventions §2 DRY).
    """
    provider_key = field_map.get(field.field_key)
    if provider_key is None:
        return []
    value = payload.get(provider_key)
    if value is None or value == "" or value == []:
        return []
    source_url = str(payload.get(url_key) or url_base)
    confidence = coerce_confidence(
        payload.get(confidence_key, default_confidence), default_confidence
    )
    return [
        resolved_field(
            field.field_key,
            value,
            source_url=source_url,
            confidence=confidence,
            use_class=use_class,
        )
    ]


def coerce_confidence(raw: object, default: float) -> float:
    """Coerce a provider-supplied confidence into the unit interval the Claim model requires.

    A tier-1 provider can return a present-but-malformed confidence (non-numeric, NaN/inf, or
    out of ``0..1``); handing that straight to the bounded ``Confidence`` type would raise a raw
    ``ValidationError`` *outside* the resolver fault taxonomy (neither a retryable fault nor a hard
    miss), aborting the run on an ordinary response. Unparseable/non-finite values fall back to the
    provider's ``default``; an out-of-range number is clamped to ``[0, 1]``.
    """
    try:
        confidence = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if not math.isfinite(confidence):
        return default
    return min(1.0, max(0.0, confidence))


class EnrichmentBackend(Protocol):
    """The swappable provider seam: turn an entity + requested field into normalized answers.

    Contract (substrate §4/§5; M4.4): return a (possibly empty) list of :class:`ResolvedField`\\s
    for the requested ``field``. An **empty** result is a *hard miss* — a correct empty+flagged
    output the waterfall advances past, never fabricated. A **transient** failure (timeout / 5xx /
    rate-limit) raises :class:`~clue_core.RetryableResolverError` so M7 retries — it must
    not be swallowed into an empty result, or a flaky provider would read as "the fact doesn't
    exist". The backend is the only place that knows the provider's API and response shape.
    """

    def fetch(self, entity: Entity, field: FieldDef) -> Sequence[ResolvedField]: ...


# Placeholder research mode per entity kind. The waterfall always overwrites research_mode with the
# run's mode in ``_finalize`` (model_copy + revalidate), so the value here only has to be coherent
# with the claim model — a profiling mode matching the entity kind is the natural, never-surfaced
# placeholder (the resolver cannot know the campaign's run mode).
_PLACEHOLDER_MODE: dict[EntityType, ResearchMode] = {
    EntityType.ACCOUNT: ResearchMode.ACCOUNT_PROFILING,
    EntityType.CONTACT: ResearchMode.CONTACT_PROFILING,
}


def build_claim(entity: Entity, resolved: ResolvedField, *, cost_cents: CostCents) -> Claim:
    """Build one tier-1 ``api`` :class:`~clue_core.Claim` from a normalized answer.

    Uses the shared provenance-enforcing constructors (``core.factories``) — never a hand-built
    ``Claim`` (the M4 invariant). ``run_id``/``research_mode`` are placeholders the engine restamps;
    a contact claim is given a ``WEAK`` identity binding the engine overwrites with the manifest's
    authoritative strength (a 3rd-party enrichment is same-name-weak unless the manifest says
    otherwise). The value is normalized through ``to_value_json`` so the jsonb payload is valid.
    """
    if entity.entity_type is EntityType.CONTACT:
        return contact_claim(
            entity_id=entity.entity_id,
            field_key=resolved.field_key,
            value_json=to_value_json(resolved.value),
            source_tier=1,
            extraction_method=ExtractionMethod.API,
            confidence=resolved.confidence,
            run_id=new_run_id(),
            research_mode=_PLACEHOLDER_MODE[entity.entity_type],
            source_url=resolved.source_url,
            evidence_span=resolved.evidence_span,
            cost_cents=cost_cents,
            identity_binding=IdentityBinding.WEAK,
            use_class=resolved.use_class,
        )
    return account_claim(
        entity_id=entity.entity_id,
        field_key=resolved.field_key,
        value_json=to_value_json(resolved.value),
        source_tier=1,
        extraction_method=ExtractionMethod.API,
        confidence=resolved.confidence,
        run_id=new_run_id(),
        research_mode=_PLACEHOLDER_MODE[entity.entity_type],
        source_url=resolved.source_url,
        evidence_span=resolved.evidence_span,
        cost_cents=cost_cents,
    )


class DeterministicResolver:
    """A tier-1 ``Resolver`` (M0.2): a thin, provider-agnostic normalizer over an injected backend.

    ``resolve`` asks the backend for the requested field and maps each normalized answer to a claim.
    The per-**call** ``cost_cents`` (the manifest's realized price for this provider) is attributed
    to the first claim only — the waterfall sums per-claim cost into the step/budget, so spreading
    the full price across a multi-value response would over-count (a per-field resolve is almost
    always a single claim, so the common case is exact). A hard miss returns ``[]``; a transient
    fault propagates as :class:`~clue_core.RetryableResolverError` from the backend.
    """

    tier: int = 1

    def __init__(self, backend: EnrichmentBackend, *, cost_cents: CostCents = Decimal(0)) -> None:
        self._backend = backend
        self._cost_cents = cost_cents

    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        resolved = list(self._backend.fetch(entity, field))
        return [
            build_claim(entity, rf, cost_cents=self._cost_cents if i == 0 else Decimal(0))
            for i, rf in enumerate(resolved)
        ]
