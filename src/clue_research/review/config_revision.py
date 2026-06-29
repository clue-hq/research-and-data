"""M13.3 — the ``config_revision`` ledger (the audited proposal/promotion record).

A learning-loop reweight emits a versioned **proposal** (``status=proposed``) carrying the full new
payload (a serialized rubric slot, or the full source-profile override slots) plus its decomposed
explanation and provenance. ``promote`` (in ``learning.py``) writes the real versioned store and
stamps the row ``promoted`` + ``applied_version``; the engine reads the stores, never this ledger.

Append-only audit: a proposal is idempotent on its ``(target, scope, parent_revision)`` lineage (so
re-proposing the same reweight is a no-op), and only the status/promotion stamps ever change.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NewType
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.core import (
    ConfigRevisionStatus,
    ConfigRevisionTarget,
    UtcDatetime,
    decode_jsonb,
    serialize_value_json,
)
from clue_research.review.reweight import WeightMove

ConfigRevisionId = NewType("ConfigRevisionId", UUID)


def new_config_revision_id() -> ConfigRevisionId:
    return ConfigRevisionId(uuid4())


class ConfigRevision(BaseModel):
    """One row of the ``config_revision`` ledger (M13.3) — a proposed/promoted/rejected reweight."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: ConfigRevisionId
    target: ConfigRevisionTarget
    client_id: str
    icp_key: str
    icp_spec_version: int
    parent_revision: ConfigRevisionId | None
    payload_json: JsonValue
    derived_from: dict[str, JsonValue] = {}
    explanation: tuple[WeightMove, ...] = ()
    within_bounds: bool = True
    status: ConfigRevisionStatus = ConfigRevisionStatus.PROPOSED
    proposed_by: str | None = None
    proposed_at: UtcDatetime
    promoted_by: str | None = None
    promoted_at: UtcDatetime | None = None
    applied_version: int | None = None


# The spec names the two proposal types distinctly; they share the ledger shape, discriminated
# by ``target`` (SourceProfileRevision → SOURCE_PROFILE, ScoringRubricRevision → SCORING_RUBRIC).
SourceProfileRevision = ConfigRevision
ScoringRubricRevision = ConfigRevision

_COLUMNS = (
    "id, target, client_id, icp_key, icp_spec_version, parent_revision, payload_json, "
    "derived_from_json, explanation_json, within_bounds, status, proposed_by, proposed_at, "
    "promoted_by, promoted_at, applied_version"
)


def _moves(raw: object) -> tuple[WeightMove, ...]:
    decoded = decode_jsonb(raw) if not isinstance(raw, (list, tuple)) else raw
    if not isinstance(decoded, (list, tuple)):
        return ()
    return tuple(WeightMove.model_validate(m) for m in decoded)


def _to_revision(row: dict[str, object]) -> ConfigRevision:
    """Parse a ``config_revision`` row — pydantic coerces the scalar columns; the jsonb columns are
    decoded first (``decode_jsonb``), and ``explanation_json`` into typed ``WeightMove``s."""
    derived = decode_jsonb(row["derived_from_json"])
    return ConfigRevision.model_validate(
        {
            "id": row["id"],
            "target": row["target"],
            "client_id": row["client_id"],
            "icp_key": row["icp_key"],
            "icp_spec_version": row["icp_spec_version"],
            "parent_revision": row["parent_revision"],
            "payload_json": decode_jsonb(row["payload_json"]),
            "derived_from": derived if isinstance(derived, dict) else {},
            "explanation": _moves(row["explanation_json"]),
            "within_bounds": row["within_bounds"],
            "status": row["status"],
            "proposed_by": row["proposed_by"],
            "proposed_at": row["proposed_at"],
            "promoted_by": row["promoted_by"],
            "promoted_at": row["promoted_at"],
            "applied_version": row["applied_version"],
        }
    )


async def record_config_revision(
    conn: AsyncConnection,
    *,
    target: ConfigRevisionTarget,
    client_id: str,
    icp_key: str,
    icp_spec_version: int,
    payload_json: JsonValue,
    parent_revision: ConfigRevisionId | None = None,
    derived_from: dict[str, JsonValue] | None = None,
    explanation: Sequence[WeightMove] = (),
    within_bounds: bool = True,
    proposed_by: str | None = None,
) -> ConfigRevision:
    """Insert a ``proposed`` revision (idempotent on the ``(target, scope, parent)`` lineage).

    A re-proposal of the same reweight returns the existing row (``ON CONFLICT DO NOTHING``), so the
    loop never duplicates a proposal. Returns the persisted :class:`ConfigRevision`."""
    inserted = (
        (
            await conn.execute(
                text(
                    f"""
                    INSERT INTO config_revision (
                        id, target, client_id, icp_key, icp_spec_version, parent_revision,
                        payload_json, derived_from_json, explanation_json, within_bounds
                    ) VALUES (
                        :id, CAST(:target AS config_revision_target), :client_id, :icp_key,
                        :icp_spec_version, :parent_revision, CAST(:payload AS jsonb),
                        CAST(:derived AS jsonb), CAST(:explanation AS jsonb), :within_bounds
                    )
                    ON CONFLICT ON CONSTRAINT config_revision_lineage DO NOTHING
                    RETURNING {_COLUMNS}
                    """
                ),
                {
                    "id": new_config_revision_id(),
                    "target": target.value,
                    "client_id": client_id,
                    "icp_key": icp_key,
                    "icp_spec_version": icp_spec_version,
                    "parent_revision": parent_revision,
                    "payload": serialize_value_json(payload_json),
                    "derived": serialize_value_json(dict(derived_from or {})),
                    "explanation": serialize_value_json(
                        [m.model_dump(mode="json") for m in explanation]
                    ),
                    "within_bounds": within_bounds,
                },
            )
        )
        .mappings()
        .first()
    )
    if inserted is not None:
        return _to_revision(dict(inserted))
    # Lineage conflict: the proposal already exists — return it (idempotent re-propose).
    existing = (
        (
            await conn.execute(
                text(
                    f"SELECT {_COLUMNS} FROM config_revision "
                    "WHERE target = CAST(:target AS config_revision_target) "
                    "AND client_id = :client_id AND icp_key = :icp_key "
                    "AND icp_spec_version = :icp_spec_version "
                    "AND parent_revision IS NOT DISTINCT FROM :parent_revision"
                ),
                {
                    "target": target.value,
                    "client_id": client_id,
                    "icp_key": icp_key,
                    "icp_spec_version": icp_spec_version,
                    "parent_revision": parent_revision,
                },
            )
        )
        .mappings()
        .one()
    )
    return _to_revision(dict(existing))


async def get_config_revision(
    conn: AsyncConnection, revision_id: ConfigRevisionId, *, for_update: bool = False
) -> ConfigRevision | None:
    """Read one revision by id. ``for_update`` takes a row lock (``SELECT … FOR UPDATE``) so a
    promotion serializes against a concurrent promote of the same revision (no double-apply)."""
    lock = " FOR UPDATE" if for_update else ""
    row = (
        (
            await conn.execute(
                text(f"SELECT {_COLUMNS} FROM config_revision WHERE id = :id{lock}"),
                {"id": revision_id},
            )
        )
        .mappings()
        .first()
    )
    return _to_revision(dict(row)) if row is not None else None


async def latest_config_revision(
    conn: AsyncConnection,
    *,
    client_id: str,
    icp_key: str,
    target: ConfigRevisionTarget,
    status: ConfigRevisionStatus | None = None,
) -> ConfigRevision | None:
    """The most recent revision for a scope+target (optionally by status) — the lineage head
    a next proposal chains off. Deterministic tie-break on ``proposed_at`` then ``id``."""
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_COLUMNS} FROM config_revision "
                    "WHERE client_id = :client_id AND icp_key = :icp_key "
                    "AND target = CAST(:target AS config_revision_target) "
                    "AND (CAST(:status AS config_revision_status) IS NULL OR status = :status) "
                    "ORDER BY proposed_at DESC, id DESC LIMIT 1"
                ),
                {
                    "client_id": client_id,
                    "icp_key": icp_key,
                    "target": target.value,
                    "status": status.value if status is not None else None,
                },
            )
        )
        .mappings()
        .first()
    )
    return _to_revision(dict(row)) if row is not None else None


async def mark_promoted(
    conn: AsyncConnection,
    revision_id: ConfigRevisionId,
    *,
    applied_version: int,
    promoted_by: str | None = None,
) -> bool:
    """Stamp a ``proposed`` revision ``promoted`` with the store version produced. Returns whether
    it transitioned (``False`` if it was not ``proposed`` — already promoted/rejected)."""
    result = await conn.execute(
        text(
            "UPDATE config_revision SET status = 'promoted', promoted_at = now(), "
            "promoted_by = :by, applied_version = :v "
            "WHERE id = :id AND status = 'proposed'"
        ),
        {"id": revision_id, "by": promoted_by, "v": applied_version},
    )
    return result.rowcount == 1


async def mark_rejected(conn: AsyncConnection, revision_id: ConfigRevisionId) -> bool:
    """Stamp a ``proposed`` revision ``rejected`` (never applied). Returns if it transitioned.

    Only the status changes — ``promoted_by``/``promoted_at`` stay NULL (a rejection is not a
    promotion; writing the rejecter into ``promoted_by`` would mislabel the audit)."""
    result = await conn.execute(
        text(
            "UPDATE config_revision SET status = 'rejected' WHERE id = :id AND status = 'proposed'"
        ),
        {"id": revision_id},
    )
    return result.rowcount == 1
