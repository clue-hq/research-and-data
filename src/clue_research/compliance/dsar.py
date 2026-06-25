"""M10.5 — data-subject rights + retention age-out, via append-only tombstones (Doc D §4).

"Stop holding this" is a first-class, queryable operation, not an assumption. Because the claim
store
is **append-only** and keyed on a resolved ``contact_entity_id``, a data-subject request resolves to
a *deterministic set* of claims — the same provenance model that makes research verifiable makes
erasure tractable (Doc D §4). Erasure is implemented **purely as supersession-by-tombstone** over
the
existing store (no new deletion path, no execution-engine-specific code — the same machinery works
under the Postgres state machine or Temporal):

* A **tombstone** is a new ``claim`` row (``extraction_method = human``, PF-5) that **supersedes**
the
  target and is written ``verification_status = REJECTED`` — so the M1.2 merge (whose
  ``_is_eligible`` excludes ``REJECTED``) can **never** serve it. Superseding the target drops it
  from
  the live set; with the only remaining live claim ineligible, ``current_value`` / the handoff
  return
  ``None`` for that field (Doc D §4 "no longer readable via ``current_value`` or handoff"), while
  the
  original row's immutable provenance is preserved in history — append-only, never a destructive
  delete (substrate §1). The tombstone's ``value_json`` is a redaction sentinel, not the real value,
  so the ineligible live row never re-exposes it (written with ``validate_field=False`` — a
  redaction
  is intentionally not a valid field value). For a ``contact.facet.*`` target it additionally
  carries
  ``identity_binding = WEAK`` (a second ineligibility mechanism) + the target's ``use_class`` (the
  DB
  CHECK + ``Claim`` validator require governance provenance on the facet class).

The four rights (the controller-scoped :class:`DataSubjectRightsImpl`):

* **access** — export the contact's claims + provenance + recorded lawful bases;
* **rectify** — supersede a claim with a corrected one (reuses the normal merge);
* **erase** — tombstone the contact's tenant-private claims (optionally scoped by use-class/field);
* **objection** (GDPR Art. 21, near-absolute) — mark the contact ``outreach_objected`` and tombstone
  its outreach hooks. Objection and retention age-out are **substrate exclusions, not use-gate
  reasons** (D-OBJ / D-EXP — there is no ``UseReason.objected``): the affected claims are tombstoned
  *before the merge read*, so the gate stays a per-claim appropriateness check and every consumer
  (``current_value``, the gate, M12) honours erasure with zero special-casing.

The **retention age-out** sweep (:class:`RetentionSweep`) is the operator-wide maintenance pass: it
consumes the frozen ``core.verification.Freshness`` seam (``due_for_age_out`` surfaces personal
claims past their *retention* horizon as ``FreshnessState.EXPIRED`` — shorter than the field
freshness TTL, Doc D §4) and tombstones them before the next merge read. Compliance may not import
``verification`` (the independence contract), so the M9.5 engine is injected as the ``core``
protocol
at the ``api`` root. Architecture: Doc D §4; docs/specs/M10-compliance-and-personal-data.md §M10.5.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import (
    ALL_TENANTS,
    claims_for,
    supersede_claim,
    supersede_claims,
)
from clue_research.compliance.lawful_basis import LawfulBasisRecord, load_lawful_basis
from clue_research.core import (
    AgeOutCandidate,
    Claim,
    ClaimId,
    EntityId,
    EntityType,
    ExtractionMethod,
    FieldClass,
    Freshness,
    IdentityBinding,
    ResearchMode,
    RunId,
    UseClass,
    UtcDatetime,
    VerificationStatus,
    classify_field_key,
    new_run_id,
)
from clue_research.db import transaction
from clue_research.identity import dsar_private_claims, stamp_reuse
from clue_research.obs import (
    ATTR_ENTITY_ID,
    SPAN_COMPLIANCE_DSAR,
    SPAN_COMPLIANCE_RETENTION_SWEEP,
    MetricSink,
    apply_attributes,
    get_logger,
    get_metric_sink,
    traced_step,
)

_log = get_logger(__name__)

# --- M10-local metric names (mirrors the M9 / M10.1 / M10.3 milestone-local pattern) ----------
METRIC_DSAR_OPERATIONS = "research.compliance.dsar.operations"  # by op
METRIC_DSAR_TOMBSTONED = "research.compliance.dsar.tombstoned"  # by reason
METRIC_RETENTION_EXPIRED = "research.compliance.retention.expired"

# --- M10-local span attribute keys (short, non-secret enum/int values) ------------------------
_ATTR_OP = "compliance.dsar.op"
_ATTR_REASON = "compliance.dsar.reason"
_ATTR_TOMBSTONED = "compliance.dsar.tombstoned"
_ATTR_SCANNED = "compliance.retention.scanned"

# The redaction sentinel a tombstone carries instead of the real value. Written with
# ``validate_field=False`` (it is intentionally not a valid field value); the tombstone is REJECTED
# so the merge never serves it regardless.
_REDACTION_SENTINEL: dict[str, bool] = {"__erased__": True}


class TombstoneReason(StrEnum):
    """Why a claim was tombstoned (M10.5; the ``dsar_tombstone.reason``). Compliance-local closed
    vocabulary stored as ``text`` + CHECK (the ``use_decision.regime`` precedent), drift-guarded
    against the migration CHECK by a no-DB test."""

    ERASURE = "erasure"  # a right-to-erasure (Art. 17) request
    OBJECTION = "objection"  # a right-to-object (Art. 21) request — outreach hooks blocked
    RETENTION_EXPIRY = "retention_expiry"  # aged out past the personal-claim retention horizon


def _now() -> datetime:
    return datetime.now(UTC)


# --- erasure scope ----------------------------------------------------------


class ErasureScope(BaseModel):
    """An optional narrowing of an erasure to a subset of a contact's claims (Doc D §4 "optionally a
    use-class/field scope"). ``None`` on a dimension means "no narrowing on that axis"; the default
    (both ``None``) erases **all** of the contact's tenant-private claims. A claim is in scope iff
    it
    matches *every* specified axis (intersection)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    use_classes: frozenset[UseClass] | None = None
    field_keys: frozenset[str] | None = None

    def matches(self, claim: Claim) -> bool:
        if self.use_classes is not None and claim.use_class not in self.use_classes:
            return False
        return not (self.field_keys is not None and str(claim.field_key) not in self.field_keys)


ERASE_ALL = ErasureScope()


# --- result value types -----------------------------------------------------


class DataSubjectExport(BaseModel):
    """The right-to-access export for one contact (M10.5): the full append-only claim history (with
    provenance) plus the recorded lawful bases, for the requesting controller only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contact_entity_id: EntityId
    tenant_id: str
    claims: tuple[Claim, ...]
    lawful_bases: tuple[LawfulBasisRecord, ...]
    exported_at: UtcDatetime


class ErasureResult(BaseModel):
    """The outcome of an :meth:`DataSubjectRightsImpl.erase` (or objection) call: the tombstones
    written and how many targets were already tombstoned (idempotent re-erasure)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contact_entity_id: EntityId
    tenant_id: str
    reason: TombstoneReason
    tombstoned_claim_ids: tuple[ClaimId, ...]
    already_tombstoned: int = 0
    scope: str | None = None


class ObjectionResult(BaseModel):
    """The outcome of an objection: whether the marker was newly set, and the hooks tombstoned."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contact_entity_id: EntityId
    tenant_id: str
    newly_objected: bool
    tombstoned_claim_ids: tuple[ClaimId, ...]


class SweepResult(BaseModel):
    """The outcome of a retention/objection sweep: how many claims were scanned and tombstoned."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: TombstoneReason
    scanned: int
    tombstoned_claim_ids: tuple[ClaimId, ...]


# --- the tombstone primitive (shared by the rights service + the sweep) -----


def build_tombstone(target: Claim, *, run_id: RunId) -> Claim:
    """The redacted, merge-ineligible claim that supersedes ``target`` (pure; DB-free).

    ``REJECTED`` is the universal ineligibility mechanism (it works for every claim type, including
    a
    plain ``contact.*`` claim whose ``identity_binding`` is ``None``); for a ``contact.facet.*``
    target the tombstone additionally carries ``identity_binding = WEAK`` (a second mechanism) and
    copies the target's ``use_class`` (the DB CHECK + ``Claim`` validator require governance
    provenance on that field-class). The tombstone inherits the target's exact tenancy (it is the
    same data subject's data for the same controller) and carries the redaction sentinel as its
    value
    — written with ``validate_field=False`` since a redaction is intentionally not a valid field
    value."""
    is_facet = classify_field_key(target.field_key) is FieldClass.CONTACT_FACET
    return Claim(
        entity_id=target.entity_id,
        entity_type=target.entity_type,
        field_key=target.field_key,
        value_json=dict(_REDACTION_SENTINEL),
        source_tier=1,
        extraction_method=ExtractionMethod.HUMAN,  # PF-5 — existing enum value, no parity change
        confidence=0.0,
        run_id=run_id,
        research_mode=ResearchMode.CONTACT_PROFILING,
        verification_status=VerificationStatus.REJECTED,  # never wins the merge (_is_eligible)
        identity_binding=IdentityBinding.WEAK if is_facet else target.identity_binding,
        use_class=target.use_class,
        reuse_scope=target.reuse_scope,
        tenant_id=target.tenant_id,
    )


async def _apply_tombstone(
    conn: AsyncConnection,
    target: Claim,
    *,
    reason: TombstoneReason,
    contact_entity_id: EntityId,
    tenant_id: str,
    run_id: RunId,
    scope_desc: str | None,
    sink: MetricSink,
) -> ClaimId | None:
    """Tombstone one **live** ``target``: record the ``dsar_tombstone`` audit row, then supersede
    the
    target with the redacted REJECTED claim. Returns the tombstone claim id, or ``None`` if the
    target was already tombstoned (idempotent — the ``dsar_tombstone.erased_claim_id`` UNIQUE).

    **Audit-first ordering** (so a concurrent double-erase cannot leave an orphan): the
    ``dsar_tombstone`` INSERT (``ON CONFLICT (erased_claim_id) DO NOTHING``) is attempted *before*
    the
    claim supersede. The UNIQUE on ``erased_claim_id`` serializes the racing transactions — the
    loser
    gets ``rowcount == 0`` and returns **without** inserting a tombstone claim, so no orphan
    redaction
    row (no back-link, no audit row) accumulates under contention. Only the winner supersedes the
    target. The tombstone claim's id is fixed up-front (``build_tombstone`` mints it) so the audit
    row
    references the exact claim the subsequent supersede inserts."""
    tombstone = build_tombstone(target, run_id=run_id)
    audit = await conn.execute(
        text(
            """
            INSERT INTO dsar_tombstone
                (erased_claim_id, tombstone_claim_id, contact_entity_id, tenant_id, reason, scope)
            VALUES
                (:erased, :tombstone, :contact, :tenant, :reason, :scope)
            ON CONFLICT (erased_claim_id) DO NOTHING
            """
        ),
        {
            "erased": str(target.id),
            "tombstone": str(tombstone.id),
            "contact": str(contact_entity_id),
            "tenant": tenant_id,
            "reason": reason.value,
            "scope": scope_desc,
        },
    )
    if audit.rowcount == 0:
        # Already tombstoned (UNIQUE conflict, incl. a concurrent winner): no claim row is written,
        # so there is no orphan; report it as already-tombstoned (the caller's count stays honest).
        return None
    # validate_field=False: the redaction sentinel is intentionally not a valid field value (the
    # tombstone is REJECTED, so it never wins the merge regardless). This is the single sanctioned
    # validate_field=False caller (documented on claimstore.supersede_claim).
    tombstone_id = await supersede_claims(conn, [target.id], tombstone, validate_field=False)
    sink.add(METRIC_DSAR_TOMBSTONED, 1, {"reason": reason.value})
    return tombstone_id


def _conn_factory_default() -> AbstractAsyncContextManager[AsyncConnection]:
    """Default connection source — one committed transaction per operation (mirrors M10.1/M10.3)."""
    return transaction()


# --- the data-subject rights service (controller-scoped) --------------------


@runtime_checkable
class DataSubjectRights(Protocol):
    """The data-subject rights surface (M10.5) — ``access`` / ``rectify`` / ``erase`` /
    ``record_objection`` for one controller. M10 supplies :class:`DataSubjectRightsImpl`; injected
    at
    the ``api`` root. (``record_objection`` is the GDPR Art. 21 right the spec lists as ``object`` —
    renamed to avoid shadowing the ``object`` builtin.)"""

    async def access(self, contact_entity_id: EntityId) -> DataSubjectExport: ...
    async def rectify(self, claim_id: ClaimId, corrected: Claim) -> ClaimId: ...
    async def erase(
        self, contact_entity_id: EntityId, scope: ErasureScope = ERASE_ALL
    ) -> ErasureResult: ...
    async def record_objection(self, contact_entity_id: EntityId) -> ObjectionResult: ...


class DataSubjectRightsImpl:
    """The M10.5 :class:`DataSubjectRights` implementation, scoped to one controller (``client_id``
    =
    ``tenant_id``). A DSAR is always for one controller, so every read uses the
    ``private_for_tenant`` selector (``identity.dsar_private_claims``) — it never touches the shared
    public base or another tenant's private data (Doc D §4). Erasure/objection are append-only
    supersession; ``access``/``rectify`` are read/merge. Each operation runs in one committed
    transaction (tests inject a rollback factory)."""

    def __init__(
        self,
        client_id: str,
        *,
        conn_factory: Callable[[], AbstractAsyncContextManager[AsyncConnection]] = (
            _conn_factory_default
        ),
        sink: MetricSink | None = None,
    ) -> None:
        self._client_id = client_id
        self._conn_factory = conn_factory
        self._sink = sink

    @property
    def _metric_sink(self) -> MetricSink:
        return self._sink or get_metric_sink()

    async def access(self, contact_entity_id: EntityId) -> DataSubjectExport:
        """Export the contact's claim history (with provenance) and recorded lawful bases — the
        right
        of access, scoped to this controller's tenant-private data. Internal **erasure tombstone**
        rows (the ``REJECTED`` ``{"__erased__": true}`` redaction markers this layer writes) are
        filtered out — they are substrate bookkeeping, not the data subject's data; the real
        superseded values remain in the export so the subject still sees *what was held* (and the
        ``dsar_tombstone`` table records *what was erased, when, and why*)."""
        with traced_step(SPAN_COMPLIANCE_DSAR, **{ATTR_ENTITY_ID: str(contact_entity_id)}) as span:
            async with self._conn_factory() as conn:
                claims = tuple(
                    c
                    for c in await dsar_private_claims(conn, contact_entity_id, self._client_id)
                    if not _is_tombstone(c)
                )
                bases: list[LawfulBasisRecord] = []
                for claim in claims:
                    record = await load_lawful_basis(conn, claim.id)
                    if record is not None:
                        bases.append(record)
            apply_attributes(span, {_ATTR_OP: "access", _ATTR_SCANNED: len(claims)})
            self._metric_sink.add(METRIC_DSAR_OPERATIONS, 1, {"op": "access"})
            return DataSubjectExport(
                contact_entity_id=contact_entity_id,
                tenant_id=self._client_id,
                claims=claims,
                lawful_bases=tuple(bases),
                exported_at=_now(),
            )

    async def rectify(self, claim_id: ClaimId, corrected: Claim) -> ClaimId:
        """Supersede ``claim_id`` with a ``corrected`` claim — the right to rectification, reusing
        the
        normal merge (the corrected claim becomes the new current value via supersession).

        **Controller-scoped, fail-closed** (consistent with ``access``/``erase``): the target must
        be
        one of *this* controller's tenant-private claims for the corrected claim's entity, else the
        rectification is refused — a controller can never supersede another tenant's claim (or a
        shared public-footprint claim) by id (the class's per-controller isolation invariant; the
        bare
        ``supersede_claim`` SQL has no tenant predicate, so the guard lives here). The corrected
        claim
        is ``stamp_reuse``-bound to this controller so it cannot be written into the wrong scope."""
        corrected = stamp_reuse(corrected, tenant_id=self._client_id)
        with traced_step(
            SPAN_COMPLIANCE_DSAR, **{ATTR_ENTITY_ID: str(corrected.entity_id)}
        ) as span:
            async with self._conn_factory() as conn:
                owned = await dsar_private_claims(conn, corrected.entity_id, self._client_id)
                if not any(c.id == claim_id for c in owned):
                    raise ValueError(
                        "rectify target is not one of this controller's tenant-private claims for "
                        "the entity — a DSAR rectification may only supersede the requesting "
                        "controller's own personal claims (fail-closed, Doc D §4)"
                    )
                new_id = await supersede_claim(conn, claim_id, corrected)
            apply_attributes(span, {_ATTR_OP: "rectify"})
            self._metric_sink.add(METRIC_DSAR_OPERATIONS, 1, {"op": "rectify"})
            return new_id

    async def erase(
        self, contact_entity_id: EntityId, scope: ErasureScope = ERASE_ALL
    ) -> ErasureResult:
        """Tombstone the contact's tenant-private claims in ``scope`` (default: all). Resolves the
        deterministic live set (``dsar_private_claims`` → live → scope filter), tombstones each, and
        records the ``dsar_tombstone`` audit. Idempotent: a re-erase finds no live claims and is a
        no-op. Afterward ``current_value`` and the handoff return none of the erased values."""
        scope_desc = _scope_desc(scope)
        run_id = new_run_id()
        with traced_step(SPAN_COMPLIANCE_DSAR, **{ATTR_ENTITY_ID: str(contact_entity_id)}) as span:
            async with self._conn_factory() as conn:
                targets = [
                    c
                    for c in await dsar_private_claims(conn, contact_entity_id, self._client_id)
                    if _erasable(c) and scope.matches(c)
                ]
                tombstoned, already = await self._tombstone_all(
                    conn,
                    targets,
                    reason=TombstoneReason.ERASURE,
                    contact_entity_id=contact_entity_id,
                    scope_desc=scope_desc,
                    run_id=run_id,
                )
            apply_attributes(
                span,
                {
                    _ATTR_OP: "erase",
                    _ATTR_REASON: TombstoneReason.ERASURE.value,
                    _ATTR_TOMBSTONED: len(tombstoned),
                },
            )
            self._metric_sink.add(METRIC_DSAR_OPERATIONS, 1, {"op": "erase"})
            return ErasureResult(
                contact_entity_id=contact_entity_id,
                tenant_id=self._client_id,
                reason=TombstoneReason.ERASURE,
                tombstoned_claim_ids=tuple(tombstoned),
                already_tombstoned=already,
                scope=scope_desc,
            )

    async def record_objection(self, contact_entity_id: EntityId) -> ObjectionResult:
        """Register a GDPR Art. 21 objection: durably mark the contact ``outreach_objected`` and
        tombstone its live ``contact.facet.*`` outreach hooks (so ``current_value``/handoff stop
        surfacing them — a substrate exclusion, D-OBJ, not a use-gate reason). Objection blocks
        outreach *use*; it is not a full erasure of the contact's structural/committee data. The
        marker lets :meth:`RetentionSweep.sweep_objections` re-suppress any hooks collected
        later."""
        run_id = new_run_id()
        with traced_step(SPAN_COMPLIANCE_DSAR, **{ATTR_ENTITY_ID: str(contact_entity_id)}) as span:
            async with self._conn_factory() as conn:
                marker = await conn.execute(
                    text(
                        """
                        INSERT INTO outreach_objected (contact_entity_id, tenant_id)
                        VALUES (:contact, :tenant)
                        ON CONFLICT (contact_entity_id, tenant_id) DO NOTHING
                        """
                    ),
                    {"contact": str(contact_entity_id), "tenant": self._client_id},
                )
                newly_objected = marker.rowcount > 0
                hooks = [
                    c
                    for c in await dsar_private_claims(conn, contact_entity_id, self._client_id)
                    if _erasable(c) and _is_outreach_hook(c)
                ]
                tombstoned, _already = await self._tombstone_all(
                    conn,
                    hooks,
                    reason=TombstoneReason.OBJECTION,
                    contact_entity_id=contact_entity_id,
                    scope_desc="contact.facet.*",
                    run_id=run_id,
                )
            apply_attributes(
                span,
                {
                    _ATTR_OP: "objection",
                    _ATTR_REASON: TombstoneReason.OBJECTION.value,
                    _ATTR_TOMBSTONED: len(tombstoned),
                },
            )
            self._metric_sink.add(METRIC_DSAR_OPERATIONS, 1, {"op": "objection"})
            return ObjectionResult(
                contact_entity_id=contact_entity_id,
                tenant_id=self._client_id,
                newly_objected=newly_objected,
                tombstoned_claim_ids=tuple(tombstoned),
            )

    async def _tombstone_all(
        self,
        conn: AsyncConnection,
        targets: Sequence[Claim],
        *,
        reason: TombstoneReason,
        contact_entity_id: EntityId,
        scope_desc: str | None,
        run_id: RunId,
    ) -> tuple[list[ClaimId], int]:
        tombstoned: list[ClaimId] = []
        already = 0
        for target in targets:
            tenant_id = target.tenant_id or self._client_id
            tombstone_id = await _apply_tombstone(
                conn,
                target,
                reason=reason,
                contact_entity_id=contact_entity_id,
                tenant_id=tenant_id,
                run_id=run_id,
                scope_desc=scope_desc,
                sink=self._metric_sink,
            )
            if tombstone_id is None:
                already += 1
            else:
                tombstoned.append(tombstone_id)
        return tombstoned, already


# --- the retention / objection sweep (operator-wide maintenance) ------------


class RetentionSweep:
    """The operator-wide retention/objection maintenance pass (M10.5). It ages out personal claims
    past their retention horizon and re-applies standing objections — both **before the merge
    read**,
    so the exclusions flow through the normal merge with zero special-casing (D-EXP / D-OBJ).

    The retention age-out consumes the frozen ``core.verification.Freshness`` seam:
    ``due_for_age_out``
    surfaces ``EXPIRED`` personal claims (past their *retention* horizon — shorter than the field
    freshness TTL, Doc D §4) and this sweep tombstones them. Compliance may not import the M9.5
    engine
    (the independence contract), so the ``Freshness`` impl is injected as the ``core`` protocol at
    the
    ``api`` root. The sweep binds each tombstone to the *claim's own* tenant (it is a cross-tenant
    maintenance op), distinct from the controller-scoped :class:`DataSubjectRightsImpl`."""

    def __init__(
        self,
        freshness: Freshness,
        *,
        conn_factory: Callable[[], AbstractAsyncContextManager[AsyncConnection]] = (
            _conn_factory_default
        ),
        sink: MetricSink | None = None,
    ) -> None:
        self._freshness = freshness
        self._conn_factory = conn_factory
        self._sink = sink

    @property
    def _metric_sink(self) -> MetricSink:
        return self._sink or get_metric_sink()

    async def sweep_expired(
        self,
        *,
        entity_ids: tuple[EntityId, ...] | None = None,
        field_keys: tuple[str, ...] | None = None,
    ) -> SweepResult:
        """Tombstone every personal claim past its retention horizon (``EXPIRED``), surfaced by the
        injected ``Freshness.due_for_age_out``, so ``current_value``/handoff stop serving it.
        Returns
        the count scanned + tombstoned. Idempotent: an already-tombstoned (superseded) claim is no
        longer live, so a re-sweep is a no-op for it."""
        candidates = await self._freshness.due_for_age_out(
            entity_ids=entity_ids,
            field_keys=tuple(field_keys) if field_keys is not None else None,
        )
        run_id = new_run_id()
        tombstoned: list[ClaimId] = []
        with traced_step(SPAN_COMPLIANCE_RETENTION_SWEEP) as span:
            async with self._conn_factory() as conn:
                for candidate in candidates:
                    tombstone_id = await self._tombstone_candidate(conn, candidate, run_id=run_id)
                    if tombstone_id is not None:
                        tombstoned.append(tombstone_id)
            apply_attributes(
                span, {_ATTR_SCANNED: len(candidates), _ATTR_TOMBSTONED: len(tombstoned)}
            )
            self._metric_sink.add(METRIC_RETENTION_EXPIRED, len(tombstoned), {})
            return SweepResult(
                reason=TombstoneReason.RETENTION_EXPIRY,
                scanned=len(candidates),
                tombstoned_claim_ids=tuple(tombstoned),
            )

    async def _tombstone_candidate(
        self, conn: AsyncConnection, candidate: AgeOutCandidate, *, run_id: RunId
    ) -> ClaimId | None:
        """Resolve the live target claim for an age-out candidate and tombstone it. The candidate
        carries only ids (no value), so the live target is fetched (operator scope) to copy its
        tenancy/use-class into the tombstone; a candidate whose claim is already superseded (raced
        with another sweep) or is itself a tombstone is skipped.

        Retention age-out is a **personal-data** operation and personal claims are tenant-private by
        construction (the ``contact.*`` field-classes default ``TENANT_PRIVATE``), so a target with
        no
        ``tenant_id`` (public-footprint) would be a non-personal claim that should never have a
        retention horizon — it is skipped rather than recorded with a degenerate empty-string
        controller in the per-controller ``dsar_tombstone`` audit."""
        live = await claims_for(conn, candidate.entity_id, candidate.field_key, scope=ALL_TENANTS)
        target = next((c for c in live if c.id == candidate.claim_id), None)
        if target is None or _is_tombstone(target):
            # already superseded / merged away since the scan, or itself a tombstone — skip
            # (idempotent; a tombstone is never aged out by a subsequent sweep)
            return None
        if target.tenant_id is None:
            # a public-footprint claim carrying a retention horizon is a contract violation
            # (personal
            # claims are tenant-private); skip + warn rather than write an un-attributable audit row
            _log.warning(
                "retention age-out skipped a public-footprint claim %s on %s — personal claims are "
                "tenant-private; a public claim should not have a retention horizon",
                candidate.claim_id,
                candidate.field_key,
            )
            return None
        return await _apply_tombstone(
            conn,
            target,
            reason=TombstoneReason.RETENTION_EXPIRY,
            contact_entity_id=candidate.entity_id,
            tenant_id=target.tenant_id,
            run_id=run_id,
            scope_desc=str(candidate.field_key),
            sink=self._metric_sink,
        )

    async def sweep_objections(self) -> SweepResult:
        """Re-apply every standing objection: for each ``outreach_objected`` contact, tombstone its
        live ``contact.facet.*`` hooks (re-suppressing hooks collected since the objection was first
        registered). Idempotent — already-tombstoned hooks are not live."""
        run_id = new_run_id()
        tombstoned: list[ClaimId] = []
        scanned = 0
        with traced_step(SPAN_COMPLIANCE_RETENTION_SWEEP) as span:
            async with self._conn_factory() as conn:
                rows = (
                    await conn.execute(
                        text("SELECT contact_entity_id, tenant_id FROM outreach_objected")
                    )
                ).all()
                for contact_raw, tenant_id in rows:
                    contact_id = EntityId(contact_raw)
                    hooks = [
                        c
                        for c in await dsar_private_claims(conn, contact_id, str(tenant_id))
                        if _erasable(c) and _is_outreach_hook(c)
                    ]
                    scanned += len(hooks)
                    for hook in hooks:
                        tombstone_id = await _apply_tombstone(
                            conn,
                            hook,
                            reason=TombstoneReason.OBJECTION,
                            contact_entity_id=contact_id,
                            tenant_id=hook.tenant_id or str(tenant_id),
                            run_id=run_id,
                            scope_desc="contact.facet.*",
                            sink=self._metric_sink,
                        )
                        if tombstone_id is not None:
                            tombstoned.append(tombstone_id)
            apply_attributes(span, {_ATTR_SCANNED: scanned, _ATTR_TOMBSTONED: len(tombstoned)})
            return SweepResult(
                reason=TombstoneReason.OBJECTION,
                scanned=scanned,
                tombstoned_claim_ids=tuple(tombstoned),
            )


# --- helpers ----------------------------------------------------------------


def _is_outreach_hook(claim: Claim) -> bool:
    """Whether a claim is an outreach personalization hook — a ``contact.facet.*`` personal claim
    (the field-class the use-gate polices). Objection blocks these; non-hook structural/committee
    claims are left intact."""
    return (
        claim.entity_type is EntityType.CONTACT
        and classify_field_key(claim.field_key) is FieldClass.CONTACT_FACET
    )


def _is_tombstone(claim: Claim) -> bool:
    """Whether a claim is itself a DSAR tombstone this layer wrote — a ``REJECTED``
    redaction-sentinel row. A tombstone supersedes its target *on the same field*, so it is a
    **live** ``contact.facet.*`` claim; without this guard a subsequent erase / objection / age-out
    pass would re-select and re-tombstone it (an unbounded loop, and a re-erase's idempotency would
    break). Identified by the sentinel value + ``REJECTED`` status — no real claim carries
    ``{"__erased__": True}``. A genuinely rejected *real* claim (e.g. faithfulness-rejected) keeps
    its real value, so it is **not** matched and is still erasable."""
    return (
        claim.verification_status is VerificationStatus.REJECTED
        and claim.value_json == _REDACTION_SENTINEL
    )


def _erasable(claim: Claim) -> bool:
    """Whether a claim is a live, non-tombstone target the rights service may tombstone."""
    return claim.superseded_by is None and not _is_tombstone(claim)


def _scope_desc(scope: ErasureScope) -> str | None:
    """A short human/audit description of an erasure scope (stored in ``dsar_tombstone.scope``)."""
    if scope.use_classes is None and scope.field_keys is None:
        return None  # the full-erasure default
    parts: list[str] = []
    if scope.use_classes is not None:
        parts.append("use_classes=" + ",".join(sorted(uc.value for uc in scope.use_classes)))
    if scope.field_keys is not None:
        parts.append("field_keys=" + ",".join(sorted(scope.field_keys)))
    return "; ".join(parts)
