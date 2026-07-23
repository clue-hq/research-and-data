"""M13.2 — the ``DispositionStore`` (capture substrate) + the concrete ``ReviewDispositionEmitter``.

Two ingest paths, one schema (spec §M13.2):

* the **internal emitter** :class:`ReviewDispositionEmitterImpl` implements the frozen
  ``core.ReviewDispositionEmitter`` seam M13.1 calls on each approve/correct/reject — it mirrors the
  durable ``review_action`` audit row into a normalized ``disposition`` (so no signal is lost), and
* the **downstream ingest** :meth:`DispositionStore.ingest_downstream` accepts a batch of client
  sales outcomes (CRM-read / webhook / manual), resolving each free-text company through identity
  (M2) to a **resolved** ``EntityId`` or **rejecting it to the error queue** — never best-guessing
  (conventions §2). The CRM is a *read* source only; this is the one inbound path into Postgres.

Every captured disposition snapshots its **contributing provenance** (the source/field/claim ids
that fed the account at handoff) into ``disposition_provenance`` — read from the persisted M12.2
``account_handoff`` (for an account-level outcome) or the single reviewed claim (for a claim-level
review action), then resolved to source/field keys via ``claimstore.claims_by_ids`` (the handoff's
``ProvenanceRef`` carries no ``source_key``/``field_key``). The snapshot is frozen at capture so a
later config change can't rewrite history (spec §M13.2 AC3).

``review`` may import shared services (``claimstore``/``identity``) + ``core``/``obs``/``db`` but
**not** ``durable``/``narrative`` (the worker-independence contract) — so the ``project_run`` ICP
context and the ``account_handoff`` provenance index are read here via **raw SQL**, not by importing
those packages. Idempotency is the DB's: ``record`` is ``INSERT … ON CONFLICT (natural_key) DO
NOTHING`` and the provenance snapshot is keyed 1:1 on ``disposition_id``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import NamedTuple
from uuid import UUID

from sqlalchemy import ARRAY, String, bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    ClaimId,
    EntityId,
    EntityType,
    ProjectRunId,
    UtcDatetime,
    serialize_value_json,
)
from clue_core.review import ReviewActionOutcome
from clue_db import ConnFactory, transaction
from clue_obs.otel import MetricSink, get_metric_sink
from clue_research.claimstore import WorkspaceScope, claims_by_ids
from clue_research.identity import (
    DEFAULT_DISPOSITION_POLICY,
    Observation,
    ResolutionMethod,
    resolve_many,
    surviving_id,
)
from clue_research.review.disposition import (
    METRIC_DISPOSITIONS,
    METRIC_DISPOSITIONS_REJECTED,
    REVIEW_ACTION_TO_DISPOSITION,
    DispositionId,
    DownstreamOutcome,
    FeedbackDisposition,
    IngestRejection,
    IngestReport,
)
from clue_research.review.labeled_dataset import LabeledRow, read_labeled_dataset

# A downstream company resolves "confidently" only at the auto-merge band (M2.3): a deterministic
# strong-key hit (domain/registry, score 1.0) or top_score ≥ auto_merge_threshold. By M2.2's
# construction a fuzzy-only match caps below that ceiling, so this admits *only* strong-key matches
# —
# everything else is rejected to the error queue, never best-guessed (conventions §2).
_RESOLVE_CONFIDENCE = DEFAULT_DISPOSITION_POLICY.auto_merge_threshold


class DispositionCaptureError(RuntimeError):
    """A review action could not be captured (e.g. its ``project_run`` is missing, so the
    disposition can't be tenant-scoped). The ``review_action`` audit row is the durable backstop —
    M13.2 can re-mirror it — so failing loud here never loses the signal."""


# --- SQL ------------------------------------------------------------------------------------------

_INSERT_DISPOSITION = text(
    """
    INSERT INTO disposition (
        id, disposition_type, entity_id, entity_type, account_entity_id, claim_id,
        project_run_id, workspace_id, icp_key, icp_spec_version, actor, origin,
        review_action_id, reason_code, detail, occurred_at, natural_key
    ) VALUES (
        :id, CAST(:disposition_type AS disposition_type), :entity_id,
        CAST(:entity_type AS entity_type), :account_entity_id, :claim_id,
        :project_run_id, :workspace_id, :icp_key, :icp_spec_version,
        CAST(:actor AS disposition_actor), CAST(:origin AS disposition_origin),
        :review_action_id, :reason_code, CAST(:detail AS jsonb), :occurred_at, :natural_key
    )
    ON CONFLICT (natural_key) DO NOTHING
    RETURNING id
    """
)

_SELECT_DISPOSITION_ID = text("SELECT id FROM disposition WHERE natural_key = :natural_key")

_INSERT_PROVENANCE = text(
    """
    INSERT INTO disposition_provenance
        (disposition_id, contributing_source_keys, contributing_field_keys, contributing_claim_ids)
    VALUES (:disposition_id, :source_keys, :field_keys, :claim_ids)
    ON CONFLICT (disposition_id) DO NOTHING
    """
).bindparams(
    bindparam("source_keys", type_=ARRAY(String())),
    bindparam("field_keys", type_=ARRAY(String())),
    bindparam("claim_ids", type_=ARRAY(String())),
)

# ICP scope from the run (review can't import ``durable``; this mirrors ``get_project_run``'s
# read).
_SELECT_RUN_CONTEXT = text(
    "SELECT workspace_id, icp_key, icp_version FROM project_run WHERE id = :id"
)

# The mirrored M13.1 audit row — the real ``occurred_at`` (``acted_at``) + the typed reject reason.
_SELECT_REVIEW_ACTION = text("SELECT reason_code, acted_at FROM review_action WHERE id = :id")

# The persisted M12.2 handoff: the contributing claim ids (provenance-index keys) + ICP context, for
# the latest assembly of this account. ``review`` can't import ``narrative``; this reads the table.
_SELECT_HANDOFF_CONTEXT = text(
    """
    SELECT icp_key, icp_spec_version, project_run_id,
           ARRAY(
               SELECT jsonb_object_keys(
                   COALESCE(payload -> 'handoff' -> 'provenance_index', '{}'::jsonb)
               )
           ) AS claim_ids
    FROM account_handoff
    WHERE workspace_id = :workspace_id AND account_entity_id = :account_entity_id
    ORDER BY assembled_at DESC
    LIMIT 1
    """
)

_TOMBSTONE_CONTACT = text(
    """
    UPDATE disposition SET tombstoned_at = now()
    WHERE entity_id = :contact_id
      AND entity_type = CAST('contact' AS entity_type)
      AND tombstoned_at IS NULL
    """
)


class _HandoffContext(NamedTuple):
    icp_key: str | None
    icp_spec_version: int | None
    project_run_id: ProjectRunId | None
    contributing_claim_ids: tuple[ClaimId, ...]


# --- conn-in primitives (the store/emitter classes are thin transaction managers over these) ------


async def record_disposition(
    conn: AsyncConnection, disposition: FeedbackDisposition
) -> tuple[DispositionId, bool]:
    """Persist ``disposition`` idempotently. Returns ``(id, was_new)`` — ``was_new`` is ``False``
    when a row with the same ``natural_key`` already existed (the caller then skips re-snapshot)."""
    detail = disposition.detail or None
    inserted = (
        await conn.execute(
            _INSERT_DISPOSITION,
            {
                "id": disposition.id,
                "disposition_type": disposition.disposition_type.value,
                "entity_id": disposition.entity_id,
                "entity_type": disposition.entity_type.value,
                "account_entity_id": disposition.account_entity_id,
                "claim_id": disposition.claim_id,
                "project_run_id": disposition.project_run_id,
                "workspace_id": disposition.workspace_id,
                "icp_key": disposition.icp_key,
                "icp_spec_version": disposition.icp_spec_version,
                "actor": disposition.actor.value,
                "origin": disposition.origin.value,
                "review_action_id": disposition.review_action_id,
                "reason_code": disposition.reason_code,
                "detail": serialize_value_json(detail) if detail is not None else None,
                "occurred_at": disposition.occurred_at,
                "natural_key": disposition.natural_key,
            },
        )
    ).first()
    if inserted is not None:
        return DispositionId(inserted[0]), True
    existing = (
        await conn.execute(_SELECT_DISPOSITION_ID, {"natural_key": disposition.natural_key})
    ).scalar_one()
    return DispositionId(existing), False


async def snapshot_claim_provenance(
    conn: AsyncConnection,
    disposition_id: DispositionId,
    claim_ids: Sequence[ClaimId],
    *,
    workspace_id: str,
) -> None:
    """Freeze the contributing source/field/claim ids for ``disposition_id`` (1:1, idempotent).

    Resolves ``claim_ids`` (the reviewed claim, or the handoff provenance-index keys) to their
    ``source_key``/``field_key`` via ``claims_by_ids`` (``ProvenanceRef`` carries neither). Source
    keys are the **distinct non-null** set (a ``human``/import claim has no source — it is not a
    source to reweight). An empty snapshot row is still written so the 1:1 invariant holds and the
    ``labeled_dataset`` view's ``LEFT JOIN`` is total. ``include_superseded`` so a corrected claim's
    original (now superseded) still resolves."""
    source_keys: list[str] = []
    field_keys: list[str] = []
    if claim_ids:
        claims = await claims_by_ids(
            conn,
            claim_ids,
            scope=WorkspaceScope.for_workspace(workspace_id),
            include_superseded=True,
        )
        source_keys = sorted({c.source_key for c in claims.values() if c.source_key})
        field_keys = sorted({str(c.field_key) for c in claims.values()})
    await conn.execute(
        _INSERT_PROVENANCE,
        {
            "disposition_id": disposition_id,
            "source_keys": source_keys,
            "field_keys": field_keys,
            "claim_ids": [str(cid) for cid in claim_ids],
        },
    )


async def _resolve_run_context(
    conn: AsyncConnection, project_run_id: ProjectRunId
) -> tuple[str, str, int] | None:
    """``(workspace_id, icp_key, icp_version)`` for a run, or ``None`` if it does not exist."""
    row = (await conn.execute(_SELECT_RUN_CONTEXT, {"id": project_run_id})).mappings().one_or_none()
    if row is None:
        return None
    return str(row["workspace_id"]), str(row["icp_key"]), int(row["icp_version"])


async def _read_review_action(
    conn: AsyncConnection, review_action_id: UUID
) -> tuple[str | None, UtcDatetime]:
    """The mirrored audit row's ``(reason_code, acted_at)`` — the occurred-time + reject reason.
    Defensive fallback ``(None, now)`` if the row is absent (it is written before the emitter runs).
    """
    row = (
        (await conn.execute(_SELECT_REVIEW_ACTION, {"id": review_action_id}))
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None, datetime.now(UTC)
    reason = row["reason_code"]
    return (str(reason) if reason is not None else None), row["acted_at"]


async def _account_handoff_context(
    conn: AsyncConnection, *, workspace_id: str, account_entity_id: EntityId
) -> _HandoffContext:
    """The latest persisted M12.2 handoff's ICP context + contributing claim ids, or empties if the
    account was never handed off (a downstream outcome on an un-handed-off account still
    records)."""
    row = (
        (
            await conn.execute(
                _SELECT_HANDOFF_CONTEXT,
                {"workspace_id": workspace_id, "account_entity_id": account_entity_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return _HandoffContext(None, None, None, ())
    raw_version = row["icp_spec_version"]
    raw_run = row["project_run_id"]
    claim_ids = tuple(ClaimId(UUID(str(s))) for s in (row["claim_ids"] or ()))
    return _HandoffContext(
        icp_key=str(row["icp_key"]) if row["icp_key"] is not None else None,
        icp_spec_version=int(raw_version) if raw_version is not None else None,
        project_run_id=ProjectRunId(raw_run) if raw_run is not None else None,
        contributing_claim_ids=claim_ids,
    )


async def capture_review_action(
    conn: AsyncConnection,
    outcome: ReviewActionOutcome,
    *,
    account_entity_id: EntityId,
    contact_entity_id: EntityId | None,
    project_run_id: ProjectRunId,
    actor: str,
    sink: MetricSink | None = None,
) -> DispositionId:
    """Mirror one M13.1 review action into a ``disposition`` (idempotent on the
    ``review_action_id``),
    snapshotting the reviewed claim's provenance. Raises :class:`DispositionCaptureError` if the run
    is missing (the audit row preserves the signal for re-mirroring)."""
    run_ctx = await _resolve_run_context(conn, project_run_id)
    if run_ctx is None:
        raise DispositionCaptureError(
            f"project_run {project_run_id} not found; cannot scope the disposition"
        )
    workspace_id, icp_key, icp_version = run_ctx
    reason_code, occurred_at = await _read_review_action(conn, outcome.review_action_id)

    if contact_entity_id is not None:
        entity_id, entity_type = contact_entity_id, EntityType.CONTACT
    else:
        entity_id, entity_type = account_entity_id, EntityType.ACCOUNT

    disposition = FeedbackDisposition.for_review_action(
        disposition_type=REVIEW_ACTION_TO_DISPOSITION[outcome.action],
        entity_id=entity_id,
        entity_type=entity_type,
        account_entity_id=account_entity_id,
        claim_id=outcome.claim_id,
        project_run_id=project_run_id,
        workspace_id=workspace_id,
        icp_key=icp_key,
        icp_spec_version=icp_version,
        review_action_id=outcome.review_action_id,
        occurred_at=occurred_at,
        reason_code=reason_code,
        detail={"reviewer": actor},
    )
    disposition_id, was_new = await record_disposition(conn, disposition)
    if was_new:
        await snapshot_claim_provenance(
            conn, disposition_id, (outcome.claim_id,), workspace_id=workspace_id
        )
        _emit_captured(disposition, sink)
    return disposition_id


async def capture_downstream(
    conn: AsyncConnection, row: DownstreamOutcome, *, sink: MetricSink | None = None
) -> DispositionId | IngestRejection:
    """Resolve one downstream outcome to a resolved account (or reject), record it, and snapshot the
    account's handoff provenance. Returns the new ``DispositionId`` or an
    :class:`IngestRejection`."""
    if row.account_entity_id is not None:
        account_id = await surviving_id(conn, row.account_entity_id, EntityType.ACCOUNT)
    else:
        observation = Observation(
            name=row.company_name,
            domain=row.domain,
            registry_ids=row.registry_ids,
            entity_type=EntityType.ACCOUNT,
        )
        result = (await resolve_many(conn, [observation], workspace_id=row.workspace_id))[0]
        top = result.top
        confident = top is not None and (
            result.method is ResolutionMethod.DETERMINISTIC
            or result.top_score >= _RESOLVE_CONFIDENCE
        )
        if top is None or not confident:
            return IngestRejection(
                external_id=row.external_id,
                disposition_type=row.disposition_type,
                reason="unresolved",
                detail=f"top_score={result.top_score:.3f} method={result.method.value}",
            )
        account_id = await surviving_id(conn, top.entity_id, EntityType.ACCOUNT)

    handoff = await _account_handoff_context(
        conn, workspace_id=row.workspace_id, account_entity_id=account_id
    )
    icp_key = row.icp_key if row.icp_key is not None else (handoff.icp_key or "")
    icp_version = (
        row.icp_spec_version if row.icp_spec_version is not None else handoff.icp_spec_version
    )
    project_run_id = row.project_run_id or handoff.project_run_id

    disposition = FeedbackDisposition.for_downstream(
        disposition_type=row.disposition_type,
        account_entity_id=account_id,
        workspace_id=row.workspace_id,
        external_id=row.external_id,
        occurred_at=row.occurred_at,
        icp_key=icp_key,
        icp_spec_version=icp_version,
        project_run_id=project_run_id,
        actor=row.actor,
        origin=row.origin,
        reason_code=row.reason_code,
        detail=row.detail,
    )
    disposition_id, was_new = await record_disposition(conn, disposition)
    if was_new:
        await snapshot_claim_provenance(
            conn, disposition_id, handoff.contributing_claim_ids, workspace_id=row.workspace_id
        )
        _emit_captured(disposition, sink)
    return disposition_id


async def ingest_downstream(
    conn: AsyncConnection, rows: Sequence[DownstreamOutcome], *, sink: MetricSink | None = None
) -> IngestReport:
    """Capture a batch of downstream outcomes — one savepoint per row so a bad/unresolvable row
    rolls back *itself* and never aborts the batch (mirrors ``identity.resolve_many``)."""
    recorded: list[DispositionId] = []
    rejected: list[IngestRejection] = []
    for row in rows:
        savepoint = await conn.begin_nested()
        try:
            outcome = await capture_downstream(conn, row, sink=sink)
        except Exception as exc:  # noqa: BLE001 — a bad row must not abort the batch (Doc B §4)
            await savepoint.rollback()
            rejection = IngestRejection(
                external_id=row.external_id,
                disposition_type=row.disposition_type,
                reason="invalid",
                detail=str(exc),
            )
            rejected.append(rejection)
            _emit_rejected(rejection, sink)
            continue
        if isinstance(outcome, IngestRejection):
            await savepoint.rollback()
            rejected.append(outcome)
            _emit_rejected(outcome, sink)
        else:
            await savepoint.commit()
            recorded.append(outcome)
    return IngestReport(recorded=tuple(recorded), rejected=tuple(rejected))


async def tombstone_contact_dispositions(conn: AsyncConnection, contact_entity_id: EntityId) -> int:
    """Stamp ``tombstoned_at`` on every (non-stamped) **contact-keyed** disposition for an erased
    contact (M10.5 / Doc D §4) — an audited marker, **not** a hard delete; the ``labeled_dataset``
    view excludes stamped rows. Account-keyed dispositions are *not* cascaded. Returns the count."""
    result = await conn.execute(_TOMBSTONE_CONTACT, {"contact_id": contact_entity_id})
    return int(result.rowcount)


# --- metrics --------------------------------------------------------------------------------------


def _emit_captured(disposition: FeedbackDisposition, sink: MetricSink | None) -> None:
    (sink or get_metric_sink()).add(
        METRIC_DISPOSITIONS,
        1.0,
        {
            "type": disposition.disposition_type.value,
            "origin": disposition.origin.value,
            "actor": disposition.actor.value,
        },
    )


def _emit_rejected(rejection: IngestRejection, sink: MetricSink | None) -> None:
    (sink or get_metric_sink()).add(METRIC_DISPOSITIONS_REJECTED, 1.0, {"reason": rejection.reason})


# --- the seam impls (wired at the api composition root) -------------------------------------------


class DispositionStore:
    """The M13.2 capture/read substrate (spec §M13.2 ``DispositionStore`` contract). Holds a
    ``conn_factory`` (one short transaction per call, like ``compliance.UseGateImpl``); tests
    inject a
    rollback-scoped factory. The downstream-outcome channel is swappable behind
    ``ingest_downstream``;
    the only read M13.3 sees is ``labeled_dataset``."""

    def __init__(
        self, *, conn_factory: ConnFactory = transaction, sink: MetricSink | None = None
    ) -> None:
        self._conn_factory = conn_factory
        self._sink = sink

    async def record(self, disposition: FeedbackDisposition) -> DispositionId:
        """Record an already-built disposition idempotently, snapshotting its provenance (the single
        claim for a ``claim_*`` type, else the account's handoff)."""
        async with self._conn_factory() as conn:
            disposition_id, was_new = await record_disposition(conn, disposition)
            if was_new:
                if disposition.claim_id is not None:
                    await snapshot_claim_provenance(
                        conn,
                        disposition_id,
                        (disposition.claim_id,),
                        workspace_id=disposition.workspace_id,
                    )
                else:
                    handoff = await _account_handoff_context(
                        conn,
                        workspace_id=disposition.workspace_id,
                        account_entity_id=disposition.account_entity_id,
                    )
                    await snapshot_claim_provenance(
                        conn,
                        disposition_id,
                        handoff.contributing_claim_ids,
                        workspace_id=disposition.workspace_id,
                    )
                _emit_captured(disposition, self._sink)
            return disposition_id

    async def ingest_downstream(self, rows: Sequence[DownstreamOutcome]) -> IngestReport:
        async with self._conn_factory() as conn:
            return await ingest_downstream(conn, rows, sink=self._sink)

    async def labeled_dataset(
        self,
        *,
        workspace_id: str,
        icp_spec_version: int | None = None,
        icp_key: str | None = None,
        project_run_id: ProjectRunId | None = None,
        since: UtcDatetime | None = None,
    ) -> list[LabeledRow]:
        async with self._conn_factory() as conn:
            return await read_labeled_dataset(
                conn,
                workspace_id=workspace_id,
                icp_spec_version=icp_spec_version,
                icp_key=icp_key,
                project_run_id=project_run_id,
                since=since,
            )

    async def tombstone_for_contact(self, contact_entity_id: EntityId) -> int:
        async with self._conn_factory() as conn:
            return await tombstone_contact_dispositions(conn, contact_entity_id)


class ReviewDispositionEmitterImpl:
    """The concrete ``core.ReviewDispositionEmitter`` (M13.2) — what the api root injects into the
    M13.1 review surface in place of the no-op. Mirrors each review action into a disposition."""

    def __init__(
        self, *, conn_factory: ConnFactory = transaction, sink: MetricSink | None = None
    ) -> None:
        self._conn_factory = conn_factory
        self._sink = sink

    async def on_review_action(
        self,
        outcome: ReviewActionOutcome,
        *,
        account_entity_id: EntityId,
        contact_entity_id: EntityId | None,
        project_run_id: ProjectRunId,
        actor: str,
    ) -> None:
        async with self._conn_factory() as conn:
            await capture_review_action(
                conn,
                outcome,
                account_entity_id=account_entity_id,
                contact_entity_id=contact_entity_id,
                project_run_id=project_run_id,
                actor=actor,
                sink=self._sink,
            )
