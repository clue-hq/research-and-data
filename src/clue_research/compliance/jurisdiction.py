"""M10.1 — Jurisdiction resolution per contact entity (D4 resolved: mixed/global).

Because target contacts are mixed/global, "which data-protection regime governs this person" must be
a first-class, evidence-backed property — the use gate (M10.3), lawful-basis selection (M10.5), and
posture relaxation (M10.4) are all *parameterized by regime* (Doc D §1). This module resolves one
queryable regime per contact from its location evidence, **fails closed to the strictest regime**
when evidence is missing or unmappable ("design for the strict case; absence never relaxes
governance" — Doc D §1), and stores the result as a ``contact.jurisdiction`` *claim* so it carries
provenance and re-resolves deterministically when a later, higher-tier location claim supersedes the
earlier one (substrate §1).

The resolution waterfall, highest-confidence first (the first mappable source wins):

1. a **contact location claim** (``current_value`` over the configured ``contact_location_fields``)
   → ``derived_from = contact_location``, claim-id provenance;
2. the resolved **contact ``geo`` column** (``ContactEntity.geo``) → ``contact_location``, no claim;
3. a **parent-account location claim** (``account_location_fields``) → ``account_hq`` w/ provenance;
4. the parent **``AccountEntity.hq_geo`` column** → ``account_hq``, no claim;
5. **nothing mappable** → the strict-default regime, ``jurisdiction_unknown = True``.

The *seam* is the regime code: M10.3/M10.4/M10.5 key only on
:class:`~clue_research.config.Jurisdiction`, never on raw geography, so the region→regime mapping
(or a future geo-IP/registry resolver) is swappable behind :class:`JurisdictionResolver` without
touching the gate. The region→regime table is versioned config
(``JurisdictionPolicy.regime_mapping``; D8), so adding a region is a config edit.

The existing :class:`~clue_research.config.Jurisdiction` enum (``gdpr``/``uk_gdpr``/``us_state``/
``global_strict``) is M0.4-frozen and reused as-is; the M10 spec's illustrative ``EU_GDPR`` regime
is this codebase's ``Jurisdiction.GDPR`` (the EU/EEA GDPR-grade regime). Architecture: Doc D §1;
docs/specs/M10-compliance-and-personal-data.md §M10.1.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import (
    TenantScope,
    claims_for,
    current_value,
    supersede_claims,
)
from clue_research.compliance.fields import CONTACT_JURISDICTION
from clue_research.config import (
    STRICT_DEFAULT_REGIME,
    Jurisdiction,
    JurisdictionPolicy,
    RegimeMapping,
    get_policy,
)
from clue_research.core import (
    Claim,
    ClaimId,
    EntityId,
    EntityType,
    ExtractionMethod,
    ResearchMode,
    RunId,
    UnitInterval,
)
from clue_research.db import transaction
from clue_research.identity import get_account, get_contact, stamp_reuse
from clue_research.obs import (
    ATTR_CLIENT_ID,
    ATTR_ENTITY_ID,
    ATTR_ENTITY_TYPE,
    SPAN_COMPLIANCE_JURISDICTION,
    MetricSink,
    apply_attributes,
    get_metric_sink,
    traced_step,
)

# --- M10-local metric names (mirrors M9's "milestone-local metric" pattern) -------------------
METRIC_JURISDICTION_RESOLVED = "research.compliance.jurisdiction.resolved"
METRIC_JURISDICTION_STRICT_DEFAULT = "research.compliance.jurisdiction.strict_default"
METRIC_JURISDICTION_UNKNOWN = "research.compliance.jurisdiction.unknown"

# --- M10-local span attribute keys (short, non-secret; coerced/passed by safe_attributes) -----
_ATTR_REGIME = "regime"
_ATTR_REGION = "region"
_ATTR_DERIVED_FROM = "derived_from"
_ATTR_JURISDICTION_UNKNOWN = "jurisdiction_unknown"


class DerivedFrom(StrEnum):
    """Where a contact's regime was derived from — the provenance axis of a resolution. Records
    *which* tier of the waterfall produced the regime so observability and downstream auditing can
    tell a contact-level resolution from an account-HQ fallback from a strict-default."""

    CONTACT_LOCATION = "contact_location"  # the contact's own location (claim or geo column)
    ACCOUNT_HQ = "account_hq"  # the parent account's HQ (location claim or hq_geo column)
    STRICT_DEFAULT = "strict_default"  # no mappable evidence — fail closed to the strict regime


class JurisdictionResolution(BaseModel):
    """The resolved data-protection regime for one contact (M10.1).

    ``regime`` is the gate-facing seam (M10.3/4/5 key on it). ``region`` is the raw ISO-3166 region
    the regime was derived from (``None`` when no location evidence was found). ``confidence`` ranks
    the source (a contact location claim outranks the contact ``geo`` column outranks an account-HQ
    fallback outranks the strict default), so a re-resolution from stronger evidence is comparable.
    ``derived_from`` records the waterfall tier; ``jurisdiction_unknown`` is set whenever the
    resolver fell through to the strict default (no mappable evidence) — the strict regime is then a
    fail-closed governance choice, **not** a confident determination. ``provenance_claim_ids`` are
    the location claim(s) the regime was read from (empty for column-derived or strict-default
    resolutions, which have no backing claim)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contact_entity_id: EntityId
    regime: Jurisdiction
    region: str | None = None
    confidence: UnitInterval
    derived_from: DerivedFrom
    jurisdiction_unknown: bool = False
    provenance_claim_ids: tuple[ClaimId, ...] = ()


@runtime_checkable
class JurisdictionResolver(Protocol):
    """Resolve one regime per contact (M10.1). M10 supplies :class:`JurisdictionResolverImpl`;
    injected at the ``api`` composition root. Keyed on the regime so a future geo-IP/registry-backed
    resolver swaps in behind this protocol without touching the gate."""

    async def resolve(self, contact_entity_id: EntityId) -> JurisdictionResolution: ...


# --- pure helpers (DB-free, unit-tested) -----------------------------------------------------


def extract_region(geo: Mapping[str, JsonValue] | None, region_keys: tuple[str, ...]) -> str | None:
    """The region (ISO-3166 alpha-2, upper-cased) from a loosely-conventional ``geo`` dict, probing
    ``region_keys`` in order. Geo dicts carry no enforced schema, so matching is case-insensitive on
    the key and the value is upper-cased for the regime lookup. ``None`` when absent."""
    if not geo:
        return None
    lowered = {str(key).lower(): value for key, value in geo.items()}
    for key in region_keys:
        value = lowered.get(key.lower())
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    return None


def region_from_value(value_json: JsonValue, region_keys: tuple[str, ...]) -> str | None:
    """The region from a location claim's ``value_json`` — either a bare region string (``"DE"``) or
    a geo object (``{"country": "DE"}``). Anything else yields ``None``."""
    if isinstance(value_json, str):
        return value_json.strip().upper() or None
    if isinstance(value_json, Mapping):
        return extract_region(value_json, region_keys)
    return None


def region_to_regime(region: str | None, mapping: RegimeMapping) -> Jurisdiction | None:
    """Map a region code to a regime via the versioned table, or ``None`` if unmapped/empty."""
    return mapping.regime_for(region)


# Confidence per waterfall source, strictly ordered so a stronger source always outranks a weaker
# one: contact-claim (≥0.70) > contact-geo-column (0.65) > account-claim (≤0.55) > account-HQ-column
# (0.35) > strict-default (0.0). Claim sources add a tier bonus (a tier-1 location outranks tier-4).
_SOURCE_BASE_CONFIDENCE: dict[str, float] = {
    "contact_claim": 0.70,
    "contact_geo": 0.65,
    "account_claim": 0.40,
    "account_hq": 0.35,
    "strict_default": 0.0,
}
_TIER_SCALED_SOURCES = frozenset({"contact_claim", "account_claim"})


def _confidence(source: str, tier: int | None = None) -> float:
    """Resolution confidence for a waterfall source, with a trust-tier bonus for claim sources."""
    base = _SOURCE_BASE_CONFIDENCE[source]
    if source in _TIER_SCALED_SOURCES and tier is not None:
        base += 0.05 * max(0, 4 - int(tier))  # tier1 +0.15 … tier4 +0.0; keeps the source ordering
    return min(1.0, base)


class JurisdictionResolverImpl:
    """The M10.1 :class:`JurisdictionResolver` implementation.

    Constructed per (client, run) context at the ``api`` root: it reads location evidence under the
    client's tenant scope, resolves the regime via the client's :class:`JurisdictionPolicy`, and (by
    default) writes the ``contact.jurisdiction`` claim — superseding any prior live one so the
    contact's regime re-resolves deterministically. ``persist=False`` returns the resolution without
    writing (used by callers that only need the regime, and by read-only tests)."""

    def __init__(
        self,
        client_id: str,
        run_id: RunId,
        *,
        policy_getter: Callable[[str], JurisdictionPolicy] = get_policy,
        conn_factory: Callable[[], AbstractAsyncContextManager[AsyncConnection]] = transaction,
        persist: bool = True,
        sink: MetricSink | None = None,
    ) -> None:
        self._client_id = client_id
        self._run_id = run_id
        self._policy_getter = policy_getter
        self._conn_factory = conn_factory
        self._persist = persist
        self._sink = sink
        self._scope = TenantScope.for_tenant(client_id)

    async def resolve(self, contact_entity_id: EntityId) -> JurisdictionResolution:
        """Resolve and (by default) store the contact's regime; emit the
        ``compliance.jurisdiction`` span + metrics."""
        policy = self._policy_getter(self._client_id)
        with traced_step(
            SPAN_COMPLIANCE_JURISDICTION,
            **{
                ATTR_ENTITY_ID: str(contact_entity_id),
                ATTR_ENTITY_TYPE: EntityType.CONTACT.value,
                ATTR_CLIENT_ID: self._client_id,
            },
        ) as span:
            async with self._conn_factory() as conn:
                resolution = await self._resolve(conn, contact_entity_id, policy)
                if self._persist:
                    await self._store(conn, resolution)
            apply_attributes(
                span,
                {
                    _ATTR_REGIME: resolution.regime.value,
                    # the raw region (on a strict-default fall-through, the last seen-but-unmapped
                    # one) — so an over-strict result caused by unmapped evidence is queryable
                    _ATTR_REGION: resolution.region,
                    _ATTR_DERIVED_FROM: resolution.derived_from.value,
                    _ATTR_JURISDICTION_UNKNOWN: resolution.jurisdiction_unknown,
                },
            )
            self._emit_metrics(resolution)
            return resolution

    async def _resolve(
        self, conn: AsyncConnection, contact_entity_id: EntityId, policy: JurisdictionPolicy
    ) -> JurisdictionResolution:
        mapping = policy.regime_mapping
        last_region: str | None = (
            None  # remember an unmappable region for the strict-default record
        )

        # 1. contact location claim(s) — provenance-backed, supersession-correct (preferred).
        for field_key in policy.contact_location_fields:
            cv = await current_value(conn, contact_entity_id, field_key, scope=self._scope)
            if cv is None:
                continue
            region = region_from_value(cv.value_json, mapping.region_keys)
            if region is None:
                continue
            last_region = region
            regime = region_to_regime(region, mapping)
            if regime is not None:
                return JurisdictionResolution(
                    contact_entity_id=contact_entity_id,
                    regime=regime,
                    region=region,
                    confidence=_confidence("contact_claim", cv.provenance.source_tier),
                    derived_from=DerivedFrom.CONTACT_LOCATION,
                    provenance_claim_ids=(cv.provenance.claim_id,),
                )

        # 2. contact entity geo column (resolved by M2; no backing claim → no provenance).
        contact = await get_contact(conn, contact_entity_id)
        if contact is not None and contact.geo:
            region = extract_region(contact.geo, mapping.region_keys)
            if region is not None:
                last_region = region
                regime = region_to_regime(region, mapping)
                if regime is not None:
                    return JurisdictionResolution(
                        contact_entity_id=contact_entity_id,
                        regime=regime,
                        region=region,
                        confidence=_confidence("contact_geo"),
                        derived_from=DerivedFrom.CONTACT_LOCATION,
                    )

        # 3 + 4. parent account fallback.
        account_id = contact.account_entity_id if contact is not None else None
        if account_id is not None:
            for field_key in policy.account_location_fields:
                cv = await current_value(conn, account_id, field_key, scope=self._scope)
                if cv is None:
                    continue
                region = region_from_value(cv.value_json, mapping.region_keys)
                if region is None:
                    continue
                last_region = region
                regime = region_to_regime(region, mapping)
                if regime is not None:
                    return JurisdictionResolution(
                        contact_entity_id=contact_entity_id,
                        regime=regime,
                        region=region,
                        confidence=_confidence("account_claim", cv.provenance.source_tier),
                        derived_from=DerivedFrom.ACCOUNT_HQ,
                        provenance_claim_ids=(cv.provenance.claim_id,),
                    )
            account = await get_account(conn, account_id)
            if account is not None and account.hq_geo:
                region = extract_region(account.hq_geo, mapping.region_keys)
                if region is not None:
                    last_region = region
                    regime = region_to_regime(region, mapping)
                    if regime is not None:
                        return JurisdictionResolution(
                            contact_entity_id=contact_entity_id,
                            regime=regime,
                            region=region,
                            confidence=_confidence("account_hq"),
                            derived_from=DerivedFrom.ACCOUNT_HQ,
                        )

        # 5. no mappable evidence → fail closed to the strict regime (Doc D §1).
        return JurisdictionResolution(
            contact_entity_id=contact_entity_id,
            regime=STRICT_DEFAULT_REGIME,
            region=last_region,
            confidence=_confidence("strict_default"),
            derived_from=DerivedFrom.STRICT_DEFAULT,
            jurisdiction_unknown=True,
        )

    def _value_json(self, resolution: JurisdictionResolution) -> dict[str, JsonValue]:
        # ``region`` is omitted when None: it is an optional field in the registered value_schema
        # (claimstore validates only present optional keys, and the schema types it a plain string —
        # see compliance/fields.py), so the strict-default path (region None) validates cleanly.
        payload: dict[str, JsonValue] = {
            "regime": resolution.regime.value,
            "confidence": float(resolution.confidence),
            "derived_from": resolution.derived_from.value,
            "jurisdiction_unknown": resolution.jurisdiction_unknown,
        }
        if resolution.region is not None:
            payload["region"] = resolution.region
        return payload

    async def _store(self, conn: AsyncConnection, resolution: JurisdictionResolution) -> ClaimId:
        """Persist the resolution as a ``contact.jurisdiction`` claim, superseding **every** prior
        live one (append-only re-resolution — no UPDATE-in-place; substrate §1). The claim is a
        *derived* fact (``source_tier=1``, ``extraction_method=human``, the M6.3 computed-claim
        precedent) and ``tenant_private`` (a named person's regime, never amortized cross-client;
        stamped via ``identity.stamp_reuse``).

        All live priors are superseded (via :func:`claimstore.supersede_claims`), not just the
        newest: although the resolver itself maintains ≤1 live ``contact.jurisdiction`` claim, a
        concurrent resolve or any stray live sibling must not survive a re-resolution and keep
        contributing to ``current_value`` — so the collapse is total and the invariant is enforced,
        not merely assumed."""
        claim = Claim(
            entity_id=resolution.contact_entity_id,
            entity_type=EntityType.CONTACT,
            field_key=CONTACT_JURISDICTION,
            value_json=self._value_json(resolution),
            source_tier=1,
            extraction_method=ExtractionMethod.HUMAN,
            confidence=resolution.confidence,
            run_id=self._run_id,
            research_mode=ResearchMode.CONTACT_PROFILING,
        )
        stamped = stamp_reuse(claim, tenant_id=self._client_id)
        prior = await claims_for(
            conn, resolution.contact_entity_id, CONTACT_JURISDICTION, scope=self._scope
        )
        return await supersede_claims(conn, [p.id for p in prior], stamped)

    def _emit_metrics(self, resolution: JurisdictionResolution) -> None:
        sink = self._sink or get_metric_sink()
        sink.add(
            METRIC_JURISDICTION_RESOLVED,
            1,
            {"regime": resolution.regime.value, "derived_from": resolution.derived_from.value},
        )
        if resolution.derived_from is DerivedFrom.STRICT_DEFAULT:
            sink.add(METRIC_JURISDICTION_STRICT_DEFAULT, 1, {"regime": resolution.regime.value})
        if resolution.jurisdiction_unknown:
            sink.add(METRIC_JURISDICTION_UNKNOWN, 1, {})
