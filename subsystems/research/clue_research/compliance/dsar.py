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

from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AgeOutCandidate,
    Claim,
    ClaimId,
    EntityId,
    EntityType,
    ExtractionMethod,
    FieldClass,
    Freshness,
    IdentityBinding,
    RunId,
    UseClass,
    UtcDatetime,
    VerificationStatus,
    classify_field_key,
    new_run_id,
)
from clue_db import ConnFactory, transaction
from clue_obs.otel import (
    ATTR_ENTITY_ID,
    SPAN_COMPLIANCE_DSAR,
    SPAN_COMPLIANCE_RETENTION_SWEEP,
    MetricSink,
    apply_attributes,
    get_logger,
    get_metric_sink,
    traced_step,
)
from clue_research.claimstore import (
    ALL_WORKSPACES,
    WorkspaceScope,
    affected_derivations,
    claims_by_ids,
    claims_for,
    redact_faithfulness_rationale,
    supersede_claim,
    supersede_claims,
)
from clue_research.compliance.lawful_basis import LawfulBasisRecord, load_lawful_basis
from clue_research.identity import dsar_private_claims, stamp_reuse
from clue_research.identity.provider import erase_provider_evidence, provider_selection_ids
from clue_storage import StorageBackend, erase_if_unreferenced, purge_erased_artifacts

_log = get_logger(__name__)

# --- M10-local metric names (mirrors the M9 / M10.1 / M10.3 milestone-local pattern) ----------
METRIC_DSAR_OPERATIONS = "research.compliance.dsar.operations"  # by op
METRIC_DSAR_TOMBSTONED = "research.compliance.dsar.tombstoned"  # by reason
METRIC_DSAR_SNAPSHOT_ERASED = "research.compliance.dsar.snapshot_erased"  # by reason (PB-B2.5)
METRIC_DSAR_FAITHFULNESS_IDENTITY_ERRORS = (
    "research.compliance.dsar.faithfulness_subject_identity.errors"
)
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
_CHANNEL_FIELDS = frozenset({"core.work_email", "core.direct_phone"})


async def _suppress_contact_channels(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    contact_entity_id: EntityId,
    reason: str,
    field_keys: frozenset[str] | None = None,
) -> None:
    channels = []
    if field_keys is None or "core.work_email" in field_keys:
        channels.append("email")
    if field_keys is None or "core.direct_phone" in field_keys:
        channels.append("phone")
    for channel in channels:
        await conn.execute(
            text(
                "INSERT INTO contact_channel_suppression "
                "(workspace_id, contact_id, channel, reason) VALUES "
                "(:workspace_id, :contact_id, CAST(:channel AS contact_channel_kind), :reason) "
                "ON CONFLICT (workspace_id, contact_id, channel) "
                "DO UPDATE SET reason=EXCLUDED.reason"
            ),
            {
                "workspace_id": workspace_id,
                "contact_id": contact_entity_id,
                "channel": channel,
                "reason": reason,
            },
        )


async def _mark_contact_channel_artifacts(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    contact_entity_id: EntityId,
    erased_keys: list[str],
    field_keys: frozenset[str] | None = None,
) -> None:
    """Sever and erase every channel-artifact edge for the in-scope Contact.

    C5 request/CSV, provider response, validation, and receipt artifacts are all explicitly bound
    to the contact. FI-2 interactive email lookup artifacts use the same subject index. Only a
    provider's final observation is also cited by a claim, so claim tombstoning alone is
    insufficient for DSAR or retention. This helper closes both copy surfaces while retaining the
    append-only ledger rows and content hashes for audit.
    """

    channels = []
    if field_keys is None or "core.work_email" in field_keys:
        channels.append("email")
    if field_keys is None or "core.direct_phone" in field_keys:
        channels.append("phone")
    if not channels:
        return
    rows = (
        (
            await conn.execute(
                text(
                    """
                    SELECT DISTINCT artifact_key FROM (
                        SELECT subject.artifact_key
                        FROM discovery_artifact_subject subject
                        JOIN contact_channel_operation operation
                          ON operation.workspace_id=subject.workspace_id
                         AND operation.id::text=subject.reference_id
                        WHERE subject.workspace_id=:workspace_id
                          AND subject.subject_kind='contact'
                          AND subject.subject_entity_id=:contact_id
                          AND subject.reference_kind LIKE 'contact_channel_%'
                          AND subject.tombstoned_at IS NULL
                          AND operation.channel::text = ANY(:channels)
                        UNION ALL
                        SELECT subject.artifact_key
                        FROM discovery_artifact_subject subject
                        JOIN contact_email_lookup lookup
                          ON lookup.workspace_id=subject.workspace_id
                         AND lookup.id::text=subject.reference_id
                        WHERE 'email' = ANY(:channels)
                          AND subject.workspace_id=:workspace_id
                          AND subject.subject_kind='contact'
                          AND subject.subject_entity_id=:contact_id
                          AND subject.reference_kind='contact_email_lookup_provider'
                          AND subject.tombstoned_at IS NULL
                    ) channel_artifacts
                    ORDER BY artifact_key
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "contact_id": contact_entity_id,
                    "channels": channels,
                },
            )
        )
        .scalars()
        .all()
    )
    await conn.execute(
        text(
            """
            UPDATE discovery_artifact_subject subject
               SET tombstoned_at=COALESCE(subject.tombstoned_at, now())
              FROM contact_channel_operation operation
             WHERE operation.workspace_id=subject.workspace_id
               AND operation.id::text=subject.reference_id
               AND subject.workspace_id=:workspace_id
               AND subject.subject_kind='contact'
               AND subject.subject_entity_id=:contact_id
               AND subject.reference_kind LIKE 'contact_channel_%'
               AND subject.tombstoned_at IS NULL
               AND operation.channel::text = ANY(:channels)
            """
        ),
        {
            "workspace_id": workspace_id,
            "contact_id": contact_entity_id,
            "channels": channels,
        },
    )
    if "email" in channels:
        await conn.execute(
            text(
                """
                UPDATE discovery_artifact_subject subject
                   SET tombstoned_at=COALESCE(subject.tombstoned_at, now())
                  FROM contact_email_lookup lookup
                 WHERE lookup.workspace_id=subject.workspace_id
                   AND lookup.id::text=subject.reference_id
                   AND subject.workspace_id=:workspace_id
                   AND subject.subject_kind='contact'
                   AND subject.subject_entity_id=:contact_id
                   AND subject.reference_kind='contact_email_lookup_provider'
                   AND subject.tombstoned_at IS NULL
                """
            ),
            {"workspace_id": workspace_id, "contact_id": contact_entity_id},
        )
    already_marked = set(erased_keys)
    for artifact_key in rows:
        if (
            await erase_if_unreferenced(conn, str(artifact_key))
            and artifact_key not in already_marked
        ):
            erased_keys.append(str(artifact_key))
            already_marked.add(str(artifact_key))


async def _mark_contact_external_research_artifacts(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    contact_entity_id: EntityId,
    erased_keys: list[str],
) -> None:
    """Sever provider and lossless-result artifact edges for one erased/objected contact."""

    erased_keys.extend(
        await erase_provider_evidence(conn, workspace_id=workspace_id, contact_id=contact_entity_id)
    )

    rows = (
        (
            await conn.execute(
                text(
                    """
                    SELECT DISTINCT subject.artifact_key
                    FROM discovery_artifact_subject subject
                    LEFT JOIN external_research_operation operation
                      ON operation.workspace_id=subject.workspace_id
                     AND operation.id::text=subject.reference_id
                    WHERE subject.workspace_id=:workspace_id
                      AND subject.subject_kind='contact'
                      AND subject.subject_entity_id=:contact_id
                      AND (
                        (subject.reference_kind LIKE 'exa_deep_%'
                         AND operation.subject_kind='contact')
                        OR subject.reference_kind IN
                           ('entity_research_result', 'entity_research_value')
                      )
                      AND subject.tombstoned_at IS NULL
                    ORDER BY subject.artifact_key
                    """
                ),
                {"workspace_id": workspace_id, "contact_id": contact_entity_id},
            )
        )
        .scalars()
        .all()
    )
    await conn.execute(
        text(
            """
            UPDATE discovery_artifact_subject subject
               SET tombstoned_at=COALESCE(subject.tombstoned_at, now())
             WHERE subject.workspace_id=:workspace_id
               AND subject.subject_kind='contact'
               AND subject.subject_entity_id=:contact_id
               AND (
                 subject.reference_kind IN
                    ('entity_research_result', 'entity_research_value')
                 OR (
                   subject.reference_kind LIKE 'exa_deep_%'
                   AND EXISTS (
                     SELECT 1 FROM external_research_operation operation
                     WHERE operation.workspace_id=subject.workspace_id
                       AND operation.id::text=subject.reference_id
                       AND operation.subject_kind='contact'
                   )
                 )
               )
               AND subject.tombstoned_at IS NULL
            """
        ),
        {"workspace_id": workspace_id, "contact_id": contact_entity_id},
    )
    already_marked = set(erased_keys)
    for artifact_key in rows:
        if (
            await erase_if_unreferenced(conn, str(artifact_key))
            and artifact_key not in already_marked
        ):
            erased_keys.append(str(artifact_key))
            already_marked.add(str(artifact_key))


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
    workspace_id: str
    claims: tuple[Claim, ...]
    lawful_bases: tuple[LawfulBasisRecord, ...]
    exported_at: UtcDatetime


class ErasureResult(BaseModel):
    """The outcome of an :meth:`DataSubjectRightsImpl.erase` (or objection) call: the tombstones
    written and how many targets were already tombstoned (idempotent re-erasure)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contact_entity_id: EntityId
    workspace_id: str
    reason: TombstoneReason
    tombstoned_claim_ids: tuple[ClaimId, ...]
    already_tombstoned: int = 0
    scope: str | None = None


class ObjectionResult(BaseModel):
    """The outcome of an objection: whether the marker was newly set, and the hooks tombstoned."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contact_entity_id: EntityId
    workspace_id: str
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
        research_mode=target.research_mode,
        verification_status=VerificationStatus.REJECTED,  # never wins the merge (_is_eligible)
        identity_binding=IdentityBinding.WEAK if is_facet else target.identity_binding,
        use_class=target.use_class,
        reuse_scope=target.reuse_scope,
        workspace_id=target.workspace_id,
        product_id=target.product_id,
    )


async def _apply_tombstone(
    conn: AsyncConnection,
    target: Claim,
    *,
    reason: TombstoneReason,
    contact_entity_id: EntityId,
    workspace_id: str,
    run_id: RunId,
    scope_desc: str | None,
    sink: MetricSink,
    erased_keys: list[str],
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
                (erased_claim_id, tombstone_claim_id, contact_entity_id, workspace_id, reason,
                 scope)
            VALUES
                (:erased, :tombstone, :contact, :tenant, :reason, :scope)
            ON CONFLICT (erased_claim_id) DO NOTHING
            """
        ),
        {
            "erased": str(target.id),
            "tombstone": str(tombstone.id),
            "contact": str(contact_entity_id),
            "tenant": workspace_id,
            "reason": reason.value,
            "scope": scope_desc,
        },
    )
    if audit.rowcount == 0:
        # Already tombstoned (UNIQUE conflict, incl. a concurrent winner): no claim row is written,
        # so there is no orphan; report it as already-tombstoned (the caller's count stays honest).
        return None
    # A faithfulness rationale may repeat attacker-controlled evidence or personal claim text.
    # Preserve the bounded verdict/model/prompt/cost audit, but erase that free-form body in the
    # same transaction as the claim tombstone. Reachability is the existing
    # faithfulness_verdict.claim_id -> claim.entity_id relation; no subject/body copy is added.
    # COALESCE keeps this one-way and idempotent if a future caller reaches an already-redacted row.
    #
    # The reader and erasure paths share the exact source-marker-aware A→(Q,A) plan. This is
    # intentionally NOT "any claim with a span": only the judged-interview producer owns Q. A
    # malformed marked claim must not block the erasure transaction; it has no reconstructable Q,
    # so redact A, emit one bounded reason, and continue fail-closed.
    identity_error = await redact_faithfulness_rationale(conn, target, reason_code=reason.value)
    if identity_error is not None:
        sink.add(
            METRIC_DSAR_FAITHFULNESS_IDENTITY_ERRORS,
            1,
            {"reason": identity_error.reason_code},
        )
        _log.warning(
            "compliance.dsar.faithfulness_subject_identity_error reason=%s claim_id=%s",
            identity_error.reason_code,
            identity_error.actual_claim_id,
        )
    # validate_field=False: the redaction sentinel is intentionally not a valid field value (the
    # tombstone is REJECTED, so it never wins the merge regardless). This is one of the sanctioned
    # compliance redaction callers documented on claimstore.supersede_claim.
    tombstone_id = await supersede_claims(conn, [target.id], tombstone, validate_field=False)
    sink.add(METRIC_DSAR_TOMBSTONED, 1, {"reason": reason.value})
    # PB-B2.5 — erasure reaches stored evidence snapshots (refcounted, ruling 2), in TWO phases.
    # The supersede above severed THIS subject's link (the tombstone copies no artifact_key, so
    # the target dropped out of the live count). Phase 1, here inside the transaction:
    # erase_if_unreferenced recounts UNDER THE ARTIFACT ROW LOCK (race-free — a concurrent
    # erasure of the other last citer, or a concurrent writer, serializes on that lock) and
    # stamps erased_at, the durable intent; the row survives as audit with source_url nulled.
    # Phase 2 — the physical storage.delete — runs AFTER this transaction commits (the caller
    # purges the collected keys), so external storage is never mutated inside a transaction
    # that could still roll back and restore the claim.
    if target.artifact_key is not None and await erase_if_unreferenced(conn, target.artifact_key):
        erased_keys.append(target.artifact_key)
    return tombstone_id


async def _purge_marked(
    conn_factory: ConnFactory,
    storage: StorageBackend | None,
    *,
    keys: Sequence[str],
    reason: TombstoneReason,
    sink: MetricSink,
    scan_all: bool = False,
) -> None:
    """Phase 2 of snapshot erasure: physically delete the blobs whose rows were marked
    ``erased_at`` by a just-committed transaction. Runs in its **own** transaction; best-effort
    — a failure (storage down, crash) leaves the durable erased-unpurged marks for the next
    purge/sweep to converge on, and must not fail the already-committed DSAR operation.
    ``scan_all`` additionally collects marks left behind by any previously crashed purge (the
    retention sweep runs with this on)."""
    if storage is None or (not keys and not scan_all):
        return
    try:
        async with conn_factory() as conn:
            result = await purge_erased_artifacts(
                conn,
                storage,
                keys=None if scan_all else tuple(keys),
                # Only the operator-wide sweep tombstones every expired row: a keyed purge
                # cleans up after its own just-committed erasure and does no fleet work on
                # other owners' rows (review I7).
                sweep_expired=scan_all,
            )
        if result.purged_keys:
            sink.add(METRIC_DSAR_SNAPSHOT_ERASED, len(result.purged_keys), {"reason": reason.value})
    except Exception:
        _log.exception(
            "snapshot purge failed after DSAR commit; erased_at marks remain durable and the "
            "next purge/retention sweep will converge (keys=%s)",
            list(keys),
        )


async def _purge_legacy_handoff_payloads(
    conn: AsyncConnection,
    *,
    contact_entity_id: EntityId,
    workspace_id: str,
) -> None:
    """Remove copied M12.2 bodies reachable from a subject while retaining row identity.

    C7.4 receipts need no special erasure mutation because they contain references only and replay
    under current claim/policy state. ``account_handoff`` predates that contract and copied
    personal values into JSONB, so its exact subject index is the bounded compatibility bridge.
    """

    await conn.execute(
        text(
            """
            UPDATE account_handoff h
            SET payload = NULL,
                legacy_payload_purged_at = COALESCE(legacy_payload_purged_at, now())
            WHERE h.workspace_id = :workspace_id
              AND h.payload IS NOT NULL
              AND EXISTS (
                  SELECT 1
                  FROM account_handoff_subject s
                  WHERE s.account_handoff_id = h.id
                    AND s.subject_entity_id = :contact_entity_id
              )
            """
        ),
        {
            "workspace_id": workspace_id,
            "contact_entity_id": str(contact_entity_id),
        },
    )


async def _erase_entity_research_runtime_payloads(
    conn: AsyncConnection,
    *,
    contact_entity_id: EntityId,
    workspace_id: str,
) -> None:
    """Redact agent journals and delete exact LangGraph threads for one erased contact.

    Journal identity, ordering, tool names, and hashes remain as audit. Personal model/tool bodies
    take the migration-governed one-way redaction transition. LangGraph checkpoints are internal
    replay state rather than audit records, so their exact globally-namespaced threads are removed.
    """

    thread_ids = tuple(
        str(value)
        for value in (
            await conn.execute(
                text(
                    """
                    SELECT DISTINCT checkpoint_thread_id
                    FROM entity_research_agent_turn
                    WHERE workspace_id=:workspace_id
                      AND subject_type='contact'
                      AND target_entity_id=:contact_entity_id
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "contact_entity_id": contact_entity_id,
                },
            )
        ).scalars()
    )
    await conn.execute(
        text(
            """
            UPDATE entity_research_agent_event event_row
            SET payload_json=jsonb_build_object('erased', true),
                payload_erased_at=COALESCE(payload_erased_at, now())
            FROM entity_research_agent_turn turn_row
            WHERE event_row.agent_turn_id=turn_row.agent_turn_id
              AND turn_row.workspace_id=:workspace_id
              AND turn_row.subject_type='contact'
              AND turn_row.target_entity_id=:contact_entity_id
              AND event_row.payload_erased_at IS NULL
            """
        ),
        {
            "workspace_id": workspace_id,
            "contact_entity_id": contact_entity_id,
        },
    )
    await conn.execute(
        text(
            """
            UPDATE entity_research_agent_turn
            SET context_json=jsonb_build_object('erased', true),
                erased_at=COALESCE(erased_at, now())
            WHERE workspace_id=:workspace_id
              AND subject_type='contact'
              AND target_entity_id=:contact_entity_id
              AND erased_at IS NULL
            """
        ),
        {
            "workspace_id": workspace_id,
            "contact_entity_id": contact_entity_id,
        },
    )
    r9_subject_index = (
        await conn.execute(text("SELECT to_regclass('entity_research_tool_batch_result_subject')"))
    ).scalar_one()
    if r9_subject_index is not None:
        await conn.execute(
            text(
                """
                UPDATE entity_research_tool_batch_event event_row
                SET result_json=jsonb_build_object('erased', true),
                    result_erased_at=COALESCE(result_erased_at, now())
                WHERE event_row.event_kind='completed'
                  AND event_row.result_erased_at IS NULL
                  AND EXISTS (
                      SELECT 1 FROM entity_research_tool_batch_result_subject subject
                      WHERE subject.event_id=event_row.event_id
                        AND subject.workspace_id=:workspace_id
                        AND subject.subject_type='contact'
                        AND subject.target_entity_id=:contact_entity_id
                  )
                """
            ),
            {
                "workspace_id": workspace_id,
                "contact_entity_id": contact_entity_id,
            },
        )
    if not thread_ids:
        return
    for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
        exists = (
            await conn.execute(text("SELECT to_regclass(:table_name)"), {"table_name": table})
        ).scalar_one()
        if exists is not None:
            await conn.execute(
                text(f"DELETE FROM {table} WHERE thread_id=ANY(:thread_ids)"),  # noqa: S608
                {"thread_ids": list(thread_ids)},
            )


async def _tombstone_with_dependents(
    conn: AsyncConnection,
    targets: Sequence[Claim],
    *,
    reason: TombstoneReason,
    contact_entity_id: EntityId,
    workspace_id: str,
    scope_desc: str | None,
    run_id: RunId,
    sink: MetricSink,
    erased_keys: list[str],
) -> tuple[list[ClaimId], int]:
    """Tombstone targets and every transitive derived value that copied their material."""

    if scope_desc is None:
        selection_ids = await provider_selection_ids(
            conn, workspace_id=workspace_id, contact_id=contact_entity_id
        )
        selections = await claims_by_ids(
            conn,
            [ClaimId(i) for i in selection_ids],
            scope=WorkspaceScope.private_for_workspace(workspace_id),
        )
        targets = [*targets, *selections.values()]
    dependent_ids = await affected_derivations(conn, [target.id for target in targets])
    dependents = await claims_by_ids(
        conn,
        dependent_ids,
        scope=WorkspaceScope.private_for_workspace(workspace_id),
    )
    expanded: dict[ClaimId, Claim] = {target.id: target for target in targets}
    expanded.update(dependents)
    tombstoned: list[ClaimId] = []
    already = 0
    for target in sorted(expanded.values(), key=lambda c: (c.artifact_key or "", str(c.id))):
        tombstone_id = await _apply_tombstone(
            conn,
            target,
            reason=reason,
            contact_entity_id=contact_entity_id,
            workspace_id=target.workspace_id or workspace_id,
            run_id=run_id,
            scope_desc=scope_desc,
            sink=sink,
            erased_keys=erased_keys,
        )
        if tombstone_id is None:
            already += 1
        else:
            tombstoned.append(tombstone_id)
    return tombstoned, already


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


@runtime_checkable
class ContactResearchPrivacyStopper(Protocol):
    """API-root seam that stops provider work when privacy authority changes."""

    async def stop(
        self,
        conn: AsyncConnection,
        *,
        workspace_id: str,
        contact_id: EntityId,
        reason_code: str,
        authority_ref: str,
        channel_field_keys: frozenset[str] | None = None,
        stop_external: bool = True,
    ) -> None: ...


class DataSubjectRightsImpl:
    """The M10.5 :class:`DataSubjectRights` implementation, scoped to one controller
    (``workspace_id``
    =
    ``workspace_id``). A DSAR is always for one controller, so every read uses the
    ``private_for_workspace`` selector (``identity.dsar_private_claims``) — it never touches the
    shared
    public base or another tenant's private data (Doc D §4). Erasure/objection are append-only
    supersession; ``access``/``rectify`` are read/merge. Each operation runs in one committed
    transaction (tests inject a rollback factory)."""

    def __init__(
        self,
        workspace_id: str,
        *,
        conn_factory: ConnFactory = transaction,
        sink: MetricSink | None = None,
        storage: StorageBackend | None = None,
        contact_research_stopper: ContactResearchPrivacyStopper | None = None,
    ) -> None:
        self._workspace_id = workspace_id
        self._conn_factory = conn_factory
        self._sink = sink
        # PB-B2.5: the durable snapshot backend erasure must reach (refcounted blob deletion).
        # Optional — injected at the api root like Freshness; None = pre-B2 behavior (no blobs).
        self._storage = storage
        self._contact_research_stopper = contact_research_stopper

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
                    for c in await dsar_private_claims(conn, contact_entity_id, self._workspace_id)
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
                workspace_id=self._workspace_id,
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
        corrected = stamp_reuse(corrected, workspace_id=self._workspace_id)
        with traced_step(
            SPAN_COMPLIANCE_DSAR, **{ATTR_ENTITY_ID: str(corrected.entity_id)}
        ) as span:
            async with self._conn_factory() as conn:
                owned = await dsar_private_claims(conn, corrected.entity_id, self._workspace_id)
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
        erased_keys: list[str] = []
        with traced_step(SPAN_COMPLIANCE_DSAR, **{ATTR_ENTITY_ID: str(contact_entity_id)}) as span:
            async with self._conn_factory() as conn:
                await conn.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                    {"key": f"contact-research:{self._workspace_id}:{contact_entity_id}"},
                )
                if scope == ERASE_ALL:
                    # Lock source identities before source artifacts, matching provider writers.
                    erased_keys.extend(
                        await erase_provider_evidence(
                            conn, workspace_id=self._workspace_id, contact_id=contact_entity_id
                        )
                    )
                targets = [
                    c
                    for c in await dsar_private_claims(conn, contact_entity_id, self._workspace_id)
                    if _erasable(c) and scope.matches(c)
                ]
                tombstoned, already = await self._tombstone_all(
                    conn,
                    targets,
                    reason=TombstoneReason.ERASURE,
                    contact_entity_id=contact_entity_id,
                    scope_desc=scope_desc,
                    run_id=run_id,
                    erased_keys=erased_keys,
                )
                erased_channel_fields = frozenset(
                    str(claim.field_key)
                    for claim in targets
                    if str(claim.field_key) in _CHANNEL_FIELDS
                )
                explicit_fields = scope.field_keys
                only_channel_fields = (
                    explicit_fields is not None
                    and bool(explicit_fields)
                    and explicit_fields.issubset(_CHANNEL_FIELDS)
                )
                if self._contact_research_stopper is not None:
                    await self._contact_research_stopper.stop(
                        conn,
                        workspace_id=self._workspace_id,
                        contact_id=contact_entity_id,
                        reason_code=TombstoneReason.ERASURE.value,
                        authority_ref=f"dsar-erasure:{run_id}",
                        channel_field_keys=(
                            erased_channel_fields if explicit_fields is not None else None
                        ),
                        stop_external=scope == ERASE_ALL or not only_channel_fields,
                    )
                if scope == ERASE_ALL or not only_channel_fields:
                    await _mark_contact_external_research_artifacts(
                        conn,
                        workspace_id=self._workspace_id,
                        contact_entity_id=contact_entity_id,
                        erased_keys=erased_keys,
                    )
                if scope == ERASE_ALL or erased_channel_fields:
                    await _suppress_contact_channels(
                        conn,
                        workspace_id=self._workspace_id,
                        contact_entity_id=contact_entity_id,
                        reason=TombstoneReason.ERASURE.value,
                        field_keys=None if scope == ERASE_ALL else erased_channel_fields,
                    )
                    await _mark_contact_channel_artifacts(
                        conn,
                        workspace_id=self._workspace_id,
                        contact_entity_id=contact_entity_id,
                        erased_keys=erased_keys,
                        field_keys=None if scope == ERASE_ALL else erased_channel_fields,
                    )
                if scope == ERASE_ALL or "core.work_email" in erased_channel_fields:
                    await conn.execute(
                        text(
                            "UPDATE contact_entity SET verified_email=NULL, "
                            "canonical_version=canonical_version+1, updated_at=now() "
                            "WHERE id=:contact_id AND workspace_id=:workspace_id "
                            "AND verified_email IS NOT NULL"
                        ),
                        {
                            "contact_id": contact_entity_id,
                            "workspace_id": self._workspace_id,
                        },
                    )
                await _purge_legacy_handoff_payloads(
                    conn,
                    contact_entity_id=contact_entity_id,
                    workspace_id=self._workspace_id,
                )
                if scope == ERASE_ALL:
                    await _erase_entity_research_runtime_payloads(
                        conn,
                        contact_entity_id=contact_entity_id,
                        workspace_id=self._workspace_id,
                    )
            # Phase 2 — the physical blob deletes, only now that the tombstones committed.
            await _purge_marked(
                self._conn_factory,
                self._storage,
                keys=erased_keys,
                reason=TombstoneReason.ERASURE,
                sink=self._metric_sink,
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
                workspace_id=self._workspace_id,
                reason=TombstoneReason.ERASURE,
                tombstoned_claim_ids=tuple(tombstoned),
                already_tombstoned=already,
                scope=scope_desc,
            )

    async def record_objection(self, contact_entity_id: EntityId) -> ObjectionResult:
        """Register a GDPR Art. 21 objection: durably mark the contact ``outreach_objected`` and
        tombstone live personal-facet and channel outreach hooks (so ``current_value``/handoff
        stop surfacing them — a substrate exclusion, D-OBJ, not a use-gate reason). Objection
        blocks outreach *use*; it is not a full erasure of structural/committee data. The marker
        lets :meth:`RetentionSweep.sweep_objections` re-suppress hooks collected later."""
        run_id = new_run_id()
        erased_keys: list[str] = []
        with traced_step(SPAN_COMPLIANCE_DSAR, **{ATTR_ENTITY_ID: str(contact_entity_id)}) as span:
            async with self._conn_factory() as conn:
                marker = await conn.execute(
                    text(
                        """
                        INSERT INTO outreach_objected (contact_entity_id, workspace_id)
                        VALUES (:contact, :tenant)
                        ON CONFLICT (contact_entity_id, workspace_id) DO NOTHING
                        """
                    ),
                    {"contact": str(contact_entity_id), "tenant": self._workspace_id},
                )
                newly_objected = marker.rowcount > 0
                if self._contact_research_stopper is not None:
                    await self._contact_research_stopper.stop(
                        conn,
                        workspace_id=self._workspace_id,
                        contact_id=contact_entity_id,
                        reason_code=TombstoneReason.OBJECTION.value,
                        authority_ref=f"outreach-objection:{run_id}",
                    )
                hooks = [
                    c
                    for c in await dsar_private_claims(conn, contact_entity_id, self._workspace_id)
                    if _erasable(c) and _is_outreach_hook(c)
                ]
                tombstoned, _already = await self._tombstone_all(
                    conn,
                    hooks,
                    reason=TombstoneReason.OBJECTION,
                    contact_entity_id=contact_entity_id,
                    scope_desc="contact.facet.*",
                    run_id=run_id,
                    erased_keys=erased_keys,
                )
                await _suppress_contact_channels(
                    conn,
                    workspace_id=self._workspace_id,
                    contact_entity_id=contact_entity_id,
                    reason=TombstoneReason.OBJECTION.value,
                )
                await _mark_contact_channel_artifacts(
                    conn,
                    workspace_id=self._workspace_id,
                    contact_entity_id=contact_entity_id,
                    erased_keys=erased_keys,
                )
                await _mark_contact_external_research_artifacts(
                    conn,
                    workspace_id=self._workspace_id,
                    contact_entity_id=contact_entity_id,
                    erased_keys=erased_keys,
                )
                await _purge_legacy_handoff_payloads(
                    conn,
                    contact_entity_id=contact_entity_id,
                    workspace_id=self._workspace_id,
                )
            await _purge_marked(
                self._conn_factory,
                self._storage,
                keys=erased_keys,
                reason=TombstoneReason.OBJECTION,
                sink=self._metric_sink,
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
                workspace_id=self._workspace_id,
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
        erased_keys: list[str],
    ) -> tuple[list[ClaimId], int]:
        return await _tombstone_with_dependents(
            conn,
            targets,
            reason=reason,
            contact_entity_id=contact_entity_id,
            workspace_id=self._workspace_id,
            scope_desc=scope_desc,
            run_id=run_id,
            sink=self._metric_sink,
            erased_keys=erased_keys,
        )


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
        conn_factory: ConnFactory = transaction,
        sink: MetricSink | None = None,
        storage: StorageBackend | None = None,
    ) -> None:
        self._freshness = freshness
        self._conn_factory = conn_factory
        self._sink = sink
        # PB-B2.5: same optional snapshot backend as DataSubjectRightsImpl (api-root injected).
        self._storage = storage

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
        erased_keys: list[str] = []
        with traced_step(SPAN_COMPLIANCE_RETENTION_SWEEP) as span:
            async with self._conn_factory() as conn:
                for candidate in candidates:
                    tombstone_ids = await self._tombstone_candidate(
                        conn, candidate, run_id=run_id, erased_keys=erased_keys
                    )
                    tombstoned.extend(tombstone_ids)
            # Phase 2 with scan_all: the sweep is the operator-wide maintenance pass, so it also
            # converges any erased-but-unpurged marks a crashed earlier purge left behind.
            await _purge_marked(
                self._conn_factory,
                self._storage,
                keys=erased_keys,
                reason=TombstoneReason.RETENTION_EXPIRY,
                sink=self._metric_sink,
                scan_all=True,
            )
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
        self,
        conn: AsyncConnection,
        candidate: AgeOutCandidate,
        *,
        run_id: RunId,
        erased_keys: list[str],
    ) -> tuple[ClaimId, ...]:
        """Resolve the live target claim for an age-out candidate and tombstone it. The candidate
        carries only ids (no value), so the live target is fetched (operator scope) to copy its
        tenancy/use-class into the tombstone; a candidate whose claim is already superseded (raced
        with another sweep) or is itself a tombstone is skipped.

        Retention age-out is a **personal-data** operation and personal claims are tenant-private by
        construction (the ``contact.*`` field-classes default ``TENANT_PRIVATE``), so a target with
        no
        ``workspace_id`` (public-footprint) would be a non-personal claim that should never have a
        retention horizon — it is skipped rather than recorded with a degenerate empty-string
        controller in the per-controller ``dsar_tombstone`` audit."""
        live = await claims_for(
            conn, candidate.entity_id, candidate.field_key, scope=ALL_WORKSPACES
        )
        target = next((c for c in live if c.id == candidate.claim_id), None)
        if target is None or _is_tombstone(target):
            # already superseded / merged away since the scan, or itself a tombstone — skip
            # (idempotent; a tombstone is never aged out by a subsequent sweep)
            return ()
        if target.workspace_id is None:
            # a public-footprint claim carrying a retention horizon is a contract violation
            # (personal
            # claims are tenant-private); skip + warn rather than write an un-attributable audit row
            _log.warning(
                "retention age-out skipped a public-footprint claim %s on %s — personal claims are "
                "tenant-private; a public claim should not have a retention horizon",
                candidate.claim_id,
                candidate.field_key,
            )
            return ()
        tombstoned, _already = await _tombstone_with_dependents(
            conn,
            (target,),
            reason=TombstoneReason.RETENTION_EXPIRY,
            contact_entity_id=candidate.entity_id,
            workspace_id=target.workspace_id,
            run_id=run_id,
            scope_desc=str(candidate.field_key),
            sink=self._metric_sink,
            erased_keys=erased_keys,
        )
        if str(candidate.field_key) in _CHANNEL_FIELDS:
            await _suppress_contact_channels(
                conn,
                workspace_id=target.workspace_id,
                contact_entity_id=candidate.entity_id,
                reason=TombstoneReason.RETENTION_EXPIRY.value,
                field_keys=frozenset({str(candidate.field_key)}),
            )
            await _mark_contact_channel_artifacts(
                conn,
                workspace_id=target.workspace_id,
                contact_entity_id=candidate.entity_id,
                erased_keys=erased_keys,
                field_keys=frozenset({str(candidate.field_key)}),
            )
            if str(candidate.field_key) == "core.work_email":
                await conn.execute(
                    text(
                        "UPDATE contact_entity SET verified_email=NULL, "
                        "canonical_version=canonical_version+1, updated_at=now() "
                        "WHERE id=:contact_id AND workspace_id=:workspace_id "
                        "AND verified_email IS NOT NULL"
                    ),
                    {
                        "contact_id": candidate.entity_id,
                        "workspace_id": target.workspace_id,
                    },
                )
        await _purge_legacy_handoff_payloads(
            conn,
            contact_entity_id=candidate.entity_id,
            workspace_id=target.workspace_id,
        )
        return tuple(tombstoned)

    async def sweep_objections(self) -> SweepResult:
        """Re-apply every standing objection: for each ``outreach_objected`` contact, tombstone its
        live ``contact.facet.*`` hooks (re-suppressing hooks collected since the objection was first
        registered). Idempotent — already-tombstoned hooks are not live."""
        run_id = new_run_id()
        tombstoned: list[ClaimId] = []
        erased_keys: list[str] = []
        scanned = 0
        with traced_step(SPAN_COMPLIANCE_RETENTION_SWEEP) as span:
            async with self._conn_factory() as conn:
                rows = (
                    await conn.execute(
                        text("SELECT contact_entity_id, workspace_id FROM outreach_objected")
                    )
                ).all()
                for contact_raw, workspace_id in rows:
                    contact_id = EntityId(contact_raw)
                    hooks = [
                        c
                        for c in await dsar_private_claims(conn, contact_id, str(workspace_id))
                        if _erasable(c) and _is_outreach_hook(c)
                    ]
                    scanned += len(hooks)
                    contact_tombstones, _already = await _tombstone_with_dependents(
                        conn,
                        hooks,
                        reason=TombstoneReason.OBJECTION,
                        contact_entity_id=contact_id,
                        workspace_id=str(workspace_id),
                        run_id=run_id,
                        scope_desc="contact.facet.*",
                        sink=self._metric_sink,
                        erased_keys=erased_keys,
                    )
                    tombstoned.extend(contact_tombstones)
                    await _suppress_contact_channels(
                        conn,
                        workspace_id=str(workspace_id),
                        contact_entity_id=contact_id,
                        reason=TombstoneReason.OBJECTION.value,
                    )
                    await _mark_contact_channel_artifacts(
                        conn,
                        workspace_id=str(workspace_id),
                        contact_entity_id=contact_id,
                        erased_keys=erased_keys,
                    )
                    await _purge_legacy_handoff_payloads(
                        conn,
                        contact_entity_id=contact_id,
                        workspace_id=str(workspace_id),
                    )
            await _purge_marked(
                self._conn_factory,
                self._storage,
                keys=erased_keys,
                reason=TombstoneReason.OBJECTION,
                sink=self._metric_sink,
            )
            apply_attributes(span, {_ATTR_SCANNED: scanned, _ATTR_TOMBSTONED: len(tombstoned)})
            return SweepResult(
                reason=TombstoneReason.OBJECTION,
                scanned=scanned,
                tombstoned_claim_ids=tuple(tombstoned),
            )


# --- helpers ----------------------------------------------------------------


def _is_outreach_hook(claim: Claim) -> bool:
    """Whether a claim is an outreach hook: a personal facet or delivery-channel claim.

    Objection blocks these; non-hook structural and committee claims are left intact.
    """
    return str(claim.field_key) in _CHANNEL_FIELDS or (
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
