"""M13.2 — the ``labeled_dataset`` read view (the training-data export M13.3 consumes).

The single contract the learning loop (M13.3) and any future model-training consumer read: one row
per disposition, joining its **outcome label** to (a) the account's decomposed Pass-A fit/intent
score snapshots (M6, the signal features — each ``ScoreComponent`` carries its evidence claim ids),
(b) the frozen **contributing-source provenance** (``disposition_provenance``, snapshotted at
capture
so a later config change can't rewrite history), and (c) the **ICP context** (M3). Nothing
downstream
reads the raw ``disposition`` tables — only this view (spec §M13.2 "swap points": the storage layout
can change without touching the loop).

Scoped by ``(workspace_id + icp_key + icp_spec_version)`` — **not** version alone: D5 restarts
``icp_spec_version`` at 1 per ``icp_key``, so version-only would pool two ICP segments (the same
reason M12's assembler matches on both). Reproducible + append-only: re-running yields the same
disposition rows (keyed on ``disposition_id``, ordered deterministically) plus any newly-captured
ones; tombstoned rows (M10.5 erasure) are excluded by the view's ``WHERE tombstoned_at IS NULL``.

The view's SQL lives in the migration (it joins ``disposition`` × ``disposition_provenance`` ×
``claim`` × ``icp_spec``); this module is the typed reader over it.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    ClaimId,
    EntityId,
    EntityType,
    ProjectRunId,
    UtcDatetime,
    decode_jsonb,
)
from clue_research.review.disposition import (
    DispositionActor,
    DispositionId,
    DispositionOrigin,
    DispositionType,
)

_VIEW_COLUMNS = (
    "disposition_id, disposition_type, actor, origin, entity_id, entity_type, account_entity_id, "
    "claim_id, project_run_id, workspace_id, icp_key, icp_spec_version, occurred_at, recorded_at, "
    "contributing_source_keys, contributing_field_keys, contributing_claim_ids, "
    "fit_score_json, intent_score_json, scoring_rubric, icp_label"
)


class LabeledRow(BaseModel):
    """One training-data row: an outcome label + its account's score-feature snapshot + the frozen
    contributing-source provenance + ICP context. The exact shape M13.3 reweights from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    disposition_id: DispositionId
    disposition_type: DispositionType
    actor: DispositionActor
    origin: DispositionOrigin
    entity_id: EntityId
    entity_type: EntityType
    account_entity_id: EntityId
    claim_id: ClaimId | None
    project_run_id: ProjectRunId | None
    workspace_id: str
    icp_key: str
    icp_spec_version: int | None
    occurred_at: UtcDatetime
    recorded_at: UtcDatetime
    # the frozen "which sources/claims fed this account at handoff time" snapshot (set semantics).
    contributing_source_keys: tuple[str, ...] = ()
    contributing_field_keys: tuple[str, ...] = ()
    contributing_claim_ids: tuple[ClaimId, ...] = ()
    # the decomposed Pass-A score snapshots (M6) for the pinned (icp_key, version); None when the
    # account was never scored under that version (e.g. a downstream outcome with no handoff link).
    fit_score_json: JsonValue | None = None
    intent_score_json: JsonValue | None = None
    # ICP context (M3): the versioned scoring rubric + label for this (client, icp_key, version).
    scoring_rubric: JsonValue | None = None
    icp_label: str | None = None


def _claim_ids(raw: object) -> tuple[ClaimId, ...]:
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(ClaimId(v if isinstance(v, UUID) else UUID(str(v))) for v in raw)


def _strs(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(str(v) for v in raw)


def _row_to_labeled(row: dict[str, object]) -> LabeledRow:
    return LabeledRow.model_validate(
        {
            "disposition_id": row["disposition_id"],
            "disposition_type": row["disposition_type"],
            "actor": row["actor"],
            "origin": row["origin"],
            "entity_id": row["entity_id"],
            "entity_type": row["entity_type"],
            "account_entity_id": row["account_entity_id"],
            "claim_id": row["claim_id"],
            "project_run_id": row["project_run_id"],
            "workspace_id": row["workspace_id"],
            "icp_key": row["icp_key"],
            "icp_spec_version": row["icp_spec_version"],
            "occurred_at": row["occurred_at"],
            "recorded_at": row["recorded_at"],
            "contributing_source_keys": _strs(row["contributing_source_keys"]),
            "contributing_field_keys": _strs(row["contributing_field_keys"]),
            "contributing_claim_ids": _claim_ids(row["contributing_claim_ids"]),
            "fit_score_json": decode_jsonb(row["fit_score_json"]),
            "intent_score_json": decode_jsonb(row["intent_score_json"]),
            "scoring_rubric": decode_jsonb(row["scoring_rubric"]),
            "icp_label": row["icp_label"],
        }
    )


async def read_labeled_dataset(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    icp_spec_version: int | None = None,
    icp_key: str | None = None,
    project_run_id: ProjectRunId | None = None,
    since: UtcDatetime | None = None,
) -> list[LabeledRow]:
    """Read the labeled dataset for a client, optionally narrowed to one ICP segment/version, one
    project run, and/or dispositions recorded ``since`` a watermark.

    ``workspace_id`` is **required** — the dataset is tenant-private (the fit/intent score claims it
    snapshots are ``tenant_private``, M2.5). Deterministic order (``recorded_at``, then
    ``disposition_id``) so the export is reproducible and a ``since`` cursor reads monotonically.
    """
    rows = (
        (
            await conn.execute(
                text(
                    f"""
                    SELECT {_VIEW_COLUMNS}
                    FROM labeled_dataset
                    WHERE workspace_id = :workspace_id
                      AND (CAST(:icp_spec_version AS int) IS NULL
                           OR icp_spec_version = :icp_spec_version)
                      AND (CAST(:icp_key AS text) IS NULL OR icp_key = :icp_key)
                      AND (CAST(:project_run_id AS uuid) IS NULL
                           OR project_run_id = :project_run_id)
                      AND (CAST(:since AS timestamptz) IS NULL OR recorded_at >= :since)
                    ORDER BY recorded_at, disposition_id
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "icp_spec_version": icp_spec_version,
                    "icp_key": icp_key,
                    "project_run_id": project_run_id,
                    "since": since,
                },
            )
        )
        .mappings()
        .all()
    )
    return [_row_to_labeled(dict(row)) for row in rows]
