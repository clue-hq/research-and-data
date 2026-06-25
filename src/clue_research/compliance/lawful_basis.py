"""M10.5 — lawful-basis recording (Doc D §4): "why are we allowed to hold this", made queryable.

Every personal claim records a **lawful basis** as provenance, so the question "why were we allowed
to hold this data" is *answered from the store*, not assumed (Doc D §4). The basis is a function of
the claim's use-class (M10.2), the contact's resolved jurisdiction (M10.1, recorded for audit), and
the client policy (M10.4 — the per-client basis strings on
:class:`~clue_research.config.LawfulBasisDefaults`):

* ``professional-public`` / ``personal-public-non-sensitive`` B2B → **legitimate interest** (GDPR
  Art. 6(1)(f)), carried with a pointer to the client's documented balancing test (the ``lia_ref``);
* ``sensitive`` (special-category, Art. 9) → **none** for outreach — there is no legitimate-interest
  basis (you would need explicit consent you do not have in cold outreach), which is exactly why the
  M10.3 gate locks ``sensitive`` regardless of posture. Recording ``none`` here makes that legal
  reality first-class.

The basis lives in the ``lawful_basis_record`` **side table** keyed on ``claim_id`` (PF-2 — settable
after the immutable claim is inserted, never a born ``claim`` column), alongside the Art. 14
``third_party_collected`` transparency flag (personal data collected from sources other than the
data
subject — almost always true in cold B2B research) and the use-class-keyed ``retention_until``
horizon (personal claims carry a *shorter* retention than firmographic facts — Doc D §4). M10.5 owns
the retention *semantics*; the horizon source is the M0.4
:class:`~clue_research.config.RetentionTtls`
placeholder (also referenced by the M9.5 freshness engine), not redefined here.

This module is the *recording* surface; the *erasure/retention enforcement* (the tombstone sweep
that
ages out an expired claim) lives in :mod:`clue_research.compliance.dsar`. Architecture: Doc D §4;
docs/specs/M10-compliance-and-personal-data.md §M10.5.
"""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.config import Jurisdiction, LawfulBasisDefaults, RetentionTtls
from clue_research.core import (
    Claim,
    ClaimId,
    ExtractionMethod,
    UseClass,
    UtcDatetime,
)
from clue_research.obs import (
    ATTR_FIELD_KEY,
    SPAN_COMPLIANCE_LAWFUL_BASIS,
    MetricSink,
    apply_attributes,
    get_metric_sink,
    traced_step,
)

# --- M10-local metric names (mirrors M9's / M10.3's milestone-local metric pattern) -----------
METRIC_LAWFUL_BASIS_RECORDED = "research.compliance.lawful_basis.recorded"
METRIC_THIRD_PARTY_COLLECTED = "research.compliance.lawful_basis.third_party"

# Module-level frozen defaults (the config models are immutable) — so the function signatures carry
# a
# singleton default rather than constructing one per call (B008). The api root injects the
# per-client
# LawfulBasisDefaults / RetentionTtls from get_policy(client_id) when wiring the M8 insert site.
_DEFAULT_LAWFUL_BASIS_DEFAULTS = LawfulBasisDefaults()
_DEFAULT_RETENTION_TTLS = RetentionTtls()

# --- M10-local span attribute keys (short, non-secret enum/bool values) -----------------------
_ATTR_LAWFUL_BASIS = "compliance.lawful_basis.basis"
_ATTR_REGIME = "compliance.lawful_basis.regime"
_ATTR_THIRD_PARTY = "compliance.lawful_basis.third_party_collected"

# Extraction methods that mean "collected from a source other than the data subject" (Art. 14): a
# web/API/synthesis source is third-party; a HUMAN/CRM-import value the client supplied is not (it
# came through the client's own relationship, not scraped from a third party). The default
# third_party_collected for a personal claim is derived from this set when the caller does not state
# it explicitly. (Mirrors core.claim._URL_REQUIRED_METHODS, deliberately a local copy so a future
# Art. 14 refinement does not couple to the URL-required policy.)
_THIRD_PARTY_METHODS = frozenset(
    {ExtractionMethod.API, ExtractionMethod.SCRAPE, ExtractionMethod.LLM_SYNTHESIS}
)


class LawfulBasis(StrEnum):
    """The lawful basis a personal claim is held/processed under (Doc D §4; GDPR Art. 6/9).

    Compliance-local closed vocabulary (it does **not** cross the M12/M13 caller boundary the way
    ``core.enums.UseReason`` does), so it lives here and is stored as ``text`` with a CHECK in
    ``lawful_basis_record`` (the ``use_decision.regime`` text-not-enum precedent), kept in lock-step
    with the migration CHECK by a no-DB drift guard."""

    LEGITIMATE_INTEREST = (
        "legitimate_interest"  # GDPR Art. 6(1)(f) — professional B2B, needs an LIA
    )
    CONSENT = "consent"  # Art. 6(1)(a) / Art. 9(2)(a) — not available in cold outreach
    NONE = (
        "none"  # no basis for outreach (sensitive/Art. 9 by default) — reinforces the M10.3 floor
    )


class LawfulBasisRecord(BaseModel):
    """The lawful-basis provenance recorded for one personal claim (M10.5; the
    ``lawful_basis_record``
    row). ``lia_ref`` points at the client's documented legitimate-interest balancing test (set only
    when the basis is legitimate interest). ``third_party_collected`` is the Art. 14 flag.
    ``retention_until`` is the use-class-keyed retention horizon (``None`` when the use-class
    carries
    no personal retention)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: ClaimId
    lawful_basis: LawfulBasis
    lia_ref: str | None
    third_party_collected: bool
    regime: Jurisdiction
    retention_until: UtcDatetime | None


# --- pure derivation (DB-free, unit-testable) -------------------------------


def _basis_string_for(use_class: UseClass, defaults: LawfulBasisDefaults) -> str | None:
    """The configured basis *string* for a **non-sensitive** use-class (the policy supplies it —
    policy-as-data). ``sensitive`` is handled by the Art. 9 hard floor in
    :func:`derive_lawful_basis`
    *before* this is reached (it is recorded ``none`` regardless of config), so ``sensitive_basis``
    is never consulted here — the floor is in code, not config."""
    if use_class is UseClass.PROFESSIONAL_PUBLIC:
        return defaults.professional_public_basis
    return defaults.personal_public_basis  # PERSONAL_PUBLIC_NON_SENSITIVE


def derive_lawful_basis(
    use_class: UseClass, defaults: LawfulBasisDefaults
) -> tuple[LawfulBasis, str | None]:
    """The lawful basis ``(basis, lia_ref)`` for a personal claim of ``use_class`` — the pure core
    (Doc D §4). The use-class drives the basis (``sensitive`` → ``none``; professional/personal →
    the client's configured basis, ``legitimate_interest`` by default); the contact's **regime** is
    *recorded* for audit (Art. 30 record-of-processing) and is the documented future per-regime
    relaxation axis, but the default mapping is regime-agnostic — legitimate interest covers
    professional B2B under GDPR and the lighter US regime alike, and the ``sensitive`` floor is
    universal. The ``lia_ref`` (the documented balancing test pointer) attaches **only** to a
    legitimate-interest basis. An unrecognised configured basis string fails loud (a typo in a
    client policy must surface, never silently fall through to a permissive basis).

    **The Art. 9 hard floor is enforced in code, not just config** (mirroring the M10.3 gate's
    in-code ``sensitive`` floor and ``JurisdictionPolicy``'s allow-map floor): ``sensitive``
    (special-category) data has **no** lawful basis for cold outreach (explicit consent is
    unavailable) — so it is recorded ``none`` regardless of any ``sensitive_basis`` a client policy
    or a config typo may carry. Otherwise a misconfiguration could falsely cite legitimate interest
    for Art. 9 data in the Art. 30 record-of-processing, which is exactly the legal reality this
    module exists to make first-class."""
    if use_class is UseClass.SENSITIVE:
        return LawfulBasis.NONE, None  # Art. 9 hard floor — never config-bypassable (Doc D §4)
    basis_string = _basis_string_for(use_class, defaults)
    if basis_string is None:
        return LawfulBasis.NONE, None
    try:
        basis = LawfulBasis(basis_string)
    except ValueError as exc:
        raise ValueError(
            f"configured lawful basis {basis_string!r} is not a recognised LawfulBasis "
            f"({[b.value for b in LawfulBasis]}) — fix the client policy (Doc D §4)"
        ) from exc
    lia_ref = defaults.lia_ref if basis is LawfulBasis.LEGITIMATE_INTEREST else None
    return basis, lia_ref


def retention_horizon_for(use_class: UseClass, retention: RetentionTtls) -> timedelta | None:
    """The personal-claim **retention horizon** for a use-class (Doc D §4 minimization) — the
    shorter
    of the personal TTLs, by sensitivity: ``sensitive`` is aged out fastest (the strictest
    minimization), ``professional-public`` is held longest, ``personal-public-non-sensitive`` in
    between. This is the *retention* horizon (when a claim must be erased), **distinct from** the
    field freshness TTL (when a claim is refresh-eligible) — a sensitive claim is expired at 30d
    even
    though its ``contact.facet`` field TTL is 90d (Doc D §4 aggressive minimization). DRY note: the
    M9.5 freshness engine (``verification.freshness.retention_horizon_for``) computes the same
    horizon
    keyed on ``(field_class, use_class)``; this use-class-only reader is the lawful-basis side and
    the
    two are tracked for consolidation onto one shared primitive (M9.5↔M10.5 backlog)."""
    if use_class is UseClass.SENSITIVE:
        return retention.sensitive_claim_ttl
    if use_class is UseClass.PROFESSIONAL_PUBLIC:
        return retention.professional_claim_ttl
    return retention.personal_claim_ttl  # PERSONAL_PUBLIC_NON_SENSITIVE


def is_third_party_collected(claim: Claim) -> bool:
    """The Art. 14 default for a claim: collected from a source *other than the data subject*
    (web/API/synthesis), vs supplied through the client's own relationship (human/CRM-import)."""
    return claim.extraction_method in _THIRD_PARTY_METHODS


# --- recording (the side-table I/O) -----------------------------------------


class NoticeReport(BaseModel):
    """The Art. 14 "notice may be owed" aggregate (Doc D §4) — the compliance owner's surface for
    how
    much personal data was collected from third parties (M10 *flags*, does not decide whether notice
    is owed). ``third_party_claims`` is the count of personal claims with ``third_party_collected``;
    ``third_party_contacts`` the distinct contacts they concern."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    third_party_claims: int
    third_party_contacts: int


async def record_lawful_basis(
    conn: AsyncConnection,
    claim: Claim,
    *,
    regime: Jurisdiction,
    defaults: LawfulBasisDefaults = _DEFAULT_LAWFUL_BASIS_DEFAULTS,
    retention: RetentionTtls = _DEFAULT_RETENTION_TTLS,
    third_party_collected: bool | None = None,
    sink: MetricSink | None = None,
) -> LawfulBasisRecord:
    """Derive and record the lawful basis for one personal ``claim`` (Doc D §4); UPSERT the
    ``lawful_basis_record`` row (settable post-insert, PF-2 — idempotent per ``claim_id``). The
    ``retention_until`` horizon is ``(observed_at or collected_at) +
    retention_horizon_for(use_class)``
    (``None`` when the use-class carries no personal retention). The reference time is
    ``observed_at`` (when the source published / was seen), falling back to ``collected_at`` — the
    **same** ``reference_time`` the M9.5 freshness engine ages out on (``merge._reference_time`` /
    ``verification.freshness.reference_time``), so the *recorded* erasure deadline this surfaces to
    the compliance owner / a DSAR access export equals the moment the retention sweep actually
    tombstones the claim (it would otherwise overstate the deadline whenever a source was published
    before it was scraped). Raises on a claim with no ``use_class`` (lawful basis is recorded only
    for use-class-tagged personal claims — M10.2 tags before this runs; a caller error, not a silent
    permissive default). Emits the ``compliance.lawful_basis`` span + metrics."""
    if claim.use_class is None:
        raise ValueError(
            "record_lawful_basis is for use-class-tagged personal claims — claim.use_class is None "
            "(M10.2 tags use_class at extraction; lawful basis is recorded after, on tagged claims)"
        )
    use_class = claim.use_class
    basis, lia_ref = derive_lawful_basis(use_class, defaults)
    third_party = (
        is_third_party_collected(claim) if third_party_collected is None else third_party_collected
    )
    horizon = retention_horizon_for(use_class, retention)
    reference_time = claim.observed_at or claim.collected_at  # mirrors merge._reference_time (M9.5)
    retention_until = reference_time + horizon if horizon is not None else None
    record = LawfulBasisRecord(
        claim_id=claim.id,
        lawful_basis=basis,
        lia_ref=lia_ref,
        third_party_collected=third_party,
        regime=regime,
        retention_until=retention_until,
    )
    with traced_step(
        SPAN_COMPLIANCE_LAWFUL_BASIS, **{ATTR_FIELD_KEY: str(claim.field_key)}
    ) as span:
        await conn.execute(
            text(
                """
                INSERT INTO lawful_basis_record
                    (claim_id, lawful_basis, lia_ref, third_party_collected, regime,
                    retention_until)
                VALUES
                    (:claim_id, :lawful_basis, :lia_ref, :third_party, :regime, :retention_until)
                ON CONFLICT (claim_id) DO UPDATE SET
                    lawful_basis = EXCLUDED.lawful_basis,
                    lia_ref = EXCLUDED.lia_ref,
                    third_party_collected = EXCLUDED.third_party_collected,
                    regime = EXCLUDED.regime,
                    retention_until = EXCLUDED.retention_until,
                    recorded_at = now()
                """
            ),
            {
                "claim_id": str(claim.id),
                "lawful_basis": basis.value,
                "lia_ref": lia_ref,
                "third_party": third_party,
                "regime": regime.value,
                "retention_until": retention_until,
            },
        )
        apply_attributes(
            span,
            {
                _ATTR_LAWFUL_BASIS: basis.value,
                _ATTR_REGIME: regime.value,
                _ATTR_THIRD_PARTY: third_party,
            },
        )
    _emit(record, sink)
    return record


def _emit(record: LawfulBasisRecord, sink: MetricSink | None) -> None:
    metric_sink = sink or get_metric_sink()
    metric_sink.add(METRIC_LAWFUL_BASIS_RECORDED, 1, {"lawful_basis": record.lawful_basis.value})
    if record.third_party_collected:
        metric_sink.add(METRIC_THIRD_PARTY_COLLECTED, 1, {})


async def load_lawful_basis(conn: AsyncConnection, claim_id: ClaimId) -> LawfulBasisRecord | None:
    """The recorded lawful basis for a claim, or ``None`` if none was recorded (DSAR access)."""
    row = (
        await conn.execute(
            text(
                "SELECT claim_id, lawful_basis, lia_ref, third_party_collected, regime, "
                "retention_until FROM lawful_basis_record WHERE claim_id = :claim_id"
            ),
            {"claim_id": str(claim_id)},
        )
    ).first()
    if row is None:
        return None
    return LawfulBasisRecord(
        claim_id=ClaimId(row[0]),
        lawful_basis=LawfulBasis(row[1]),
        lia_ref=row[2],
        third_party_collected=bool(row[3]),
        regime=Jurisdiction(row[4]),
        retention_until=row[5],
    )


async def third_party_notice_report(
    conn: AsyncConnection, *, tenant_id: str | None = None
) -> NoticeReport:
    """The Art. 14 "notice may be owed" aggregate (Doc D §4): how many **currently-held** personal
    claims (and distinct contacts) carry ``third_party_collected``. Scoped to one controller's
    claims
    when ``tenant_id`` is given (a DSAR/controller view), else platform-wide (the operator view).
    Joins to ``claim`` for the tenant/contact dimensions (``lawful_basis_record`` keys only on
    ``claim_id``).

    Counts only **live** claims (``superseded_by IS NULL``) — ``lawful_basis_record`` survives a
    claim's supersession by design (no FK), so without this filter an erased (tombstoned) or
    rectified-superseded claim would still be counted, reporting data the controller has already
    erased as still held. The whole M10.5 design excludes erased/expired claims at the merge-read
    substrate (the live filter); this advisory aggregate honours the same exclusion rather than
    diverging into a historical-collection count."""
    row = (
        await conn.execute(
            text(
                """
                SELECT count(*) AS claims, count(DISTINCT c.entity_id) AS contacts
                FROM lawful_basis_record r
                JOIN claim c ON c.id = r.claim_id
                WHERE r.third_party_collected
                  AND c.superseded_by IS NULL
                  AND (CAST(:tenant_id AS text) IS NULL OR c.tenant_id = :tenant_id)
                """
            ),
            {"tenant_id": tenant_id},
        )
    ).first()
    if row is None:  # pragma: no cover — count(*) always returns one row
        return NoticeReport(third_party_claims=0, third_party_contacts=0)
    return NoticeReport(third_party_claims=int(row[0]), third_party_contacts=int(row[1]))
