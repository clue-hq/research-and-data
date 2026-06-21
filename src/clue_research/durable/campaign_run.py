"""The ``campaign_run`` / ``campaign_phase_checkpoint`` / ``adjustment_journal`` repository (M7.3).

The only sanctioned path to the three outer-state-machine tables, mirroring the ``account_run``
repository shape (``durable/account_run.py``) and the claim store (``claimstore/claims.py``):
module-level ``text(...)`` statements + ``async def`` helpers that take an
:class:`~sqlalchemy.ext.asyncio.AsyncConnection`. No caller hand-writes SQL against these tables.

``campaign_run`` is **mutable** execution state (``phase``/``status``/``tier_cutoffs`` advance over
the run's life), like ``account_run`` — the claim store keeps immutable history; this is the
resumable cursor over it. ``campaign_phase_checkpoint`` is upserted on the natural
``(campaign_run_id, phase)`` key (the frozen idempotency shape), so a re-entered phase deduplicates
onto one row. ``adjustment_journal`` is **append-only** (DB-enforced by a reject trigger) — its rows
are never mutated. JSONB columns round-trip through the one ``core`` serialization path.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.core import (
    CampaignPhase,
    CampaignRunId,
    CostCents,
    UtcDatetime,
    parse_value_json,
    serialize_value_json,
)
from clue_research.durable.enums import CampaignRunStatus, PhaseCheckpointStatus

# Tier-cutoff config carried on the run (e.g. {"top": 0.8, "high": 0.6}); a plain JSONB object the
# tiering phase (M6.4) reads and the client adjusts at the checkpoint.
TierCutoffs = dict[str, JsonValue]


class CampaignRunRow(BaseModel):
    """A ``campaign_run`` row reconstructed from the table (M7.3) — the outer durable job."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: CampaignRunId
    client_id: str
    icp_key: str
    icp_version: int
    phase: CampaignPhase
    status: CampaignRunStatus
    budget_cap_cents: CostCents | None
    spent_cents: CostCents
    tier_cutoffs: TierCutoffs
    paused_at: UtcDatetime | None
    resumed_at: UtcDatetime | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class CampaignPhaseCheckpointRow(BaseModel):
    """A ``campaign_phase_checkpoint`` row (M7.3). ``payload`` is the phase handler's
    :class:`~clue_research.core.PhaseResult` payload by reference — and, for ``tier_checkpoint``,
    the M6.4 review payload the surface reads back (proposed cutoffs / tier distribution / cost
    estimate / decision)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    campaign_run_id: CampaignRunId
    phase: CampaignPhase
    idempotency_key: str
    status: PhaseCheckpointStatus
    payload: dict[str, JsonValue]
    committed_at: UtcDatetime | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class AdjustmentRow(BaseModel):
    """One append-only ``adjustment_journal`` row (M7.3) — an audited client ``adjust`` action."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    campaign_run_id: CampaignRunId
    kind: str
    detail: dict[str, JsonValue]
    created_at: UtcDatetime


# --- campaign_run --------------------------------------------------------------------------------

_RUN_COLUMNS = (
    "id, client_id, icp_key, icp_version, phase, status, budget_cap_cents, spent_cents, "
    "tier_cutoffs_json, paused_at, resumed_at, created_at, updated_at"
)

_ENSURE_RUN_SQL = text(
    """
    INSERT INTO campaign_run (
        id, client_id, icp_key, icp_version, phase, status, budget_cap_cents, tier_cutoffs_json
    )
    VALUES (
        :id, :client_id, :icp_key, :icp_version,
        CAST(:phase AS campaign_phase), CAST(:status AS campaign_run_status),
        :budget_cap_cents, CAST(:tier_cutoffs AS jsonb)
    )
    ON CONFLICT (id) DO NOTHING
    """
)

_GET_RUN_SQL = text(f"SELECT {_RUN_COLUMNS} FROM campaign_run WHERE id = :id")


async def ensure_campaign_run(
    conn: AsyncConnection,
    *,
    campaign_run_id: CampaignRunId,
    client_id: str,
    icp_key: str,
    icp_version: int,
    budget_cap_cents: CostCents | None = None,
    tier_cutoffs: TierCutoffs | None = None,
    phase: CampaignPhase = CampaignPhase.REVERSE_PROFILING,
    status: CampaignRunStatus = CampaignRunStatus.ACTIVE,
) -> None:
    """Insert the ``campaign_run`` row if absent (``ON CONFLICT (id) DO NOTHING``).

    Idempotent on the supplied id so ``CampaignRun.start`` is safe to call twice (a re-entry never
    resets a run that already advanced). The id is supplied by the caller (minted once via
    :func:`~clue_research.core.new_campaign_run_id`) so it is stable across a crash-and-resume."""
    await conn.execute(
        _ENSURE_RUN_SQL,
        {
            "id": campaign_run_id,
            "client_id": client_id,
            "icp_key": icp_key,
            "icp_version": icp_version,
            "budget_cap_cents": budget_cap_cents,
            "tier_cutoffs": serialize_value_json(tier_cutoffs if tier_cutoffs is not None else {}),
            "phase": phase.value,
            "status": status.value,
        },
    )


async def get_campaign_run(
    conn: AsyncConnection, campaign_run_id: CampaignRunId
) -> CampaignRunRow | None:
    """Return the ``campaign_run`` row, or ``None`` if it does not exist."""
    row = (await conn.execute(_GET_RUN_SQL, {"id": campaign_run_id})).mappings().one_or_none()
    return _row_to_campaign_run(dict(row)) if row is not None else None


async def set_phase(
    conn: AsyncConnection,
    campaign_run_id: CampaignRunId,
    *,
    phase: CampaignPhase,
    status: CampaignRunStatus,
) -> None:
    """Advance the run to ``phase`` with run-level ``status`` (the phase-transition write)."""
    await conn.execute(
        text(
            """
            UPDATE campaign_run
            SET phase = CAST(:phase AS campaign_phase),
                status = CAST(:status AS campaign_run_status),
                updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": campaign_run_id, "phase": phase.value, "status": status.value},
    )


async def set_run_status(
    conn: AsyncConnection,
    campaign_run_id: CampaignRunId,
    *,
    status: CampaignRunStatus,
    stamp_paused: bool = False,
    stamp_resumed: bool = False,
) -> None:
    """Set only the run-level ``status`` (phase unchanged), optionally stamping ``paused_at`` /
    ``resumed_at`` to ``now()`` — the pause/resume bookkeeping."""
    paused = ", paused_at = now()" if stamp_paused else ""
    resumed = ", resumed_at = now()" if stamp_resumed else ""
    await conn.execute(
        text(
            f"""
            UPDATE campaign_run
            SET status = CAST(:status AS campaign_run_status){paused}{resumed},
                updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": campaign_run_id, "status": status.value},
    )


async def set_icp_version(
    conn: AsyncConnection, campaign_run_id: CampaignRunId, icp_version: int
) -> None:
    """Re-point the run at a new ICP-spec version (M3 re-versions the spec; M7.3 records which
    version the next phase compiles against — the ``adjust(icp_version=…)`` write)."""
    await conn.execute(
        text("UPDATE campaign_run SET icp_version = :v, updated_at = now() WHERE id = :id"),
        {"id": campaign_run_id, "v": icp_version},
    )


async def set_budget_cap(
    conn: AsyncConnection, campaign_run_id: CampaignRunId, budget_cap_cents: CostCents
) -> None:
    """Set the per-campaign hard cap (the ``adjust(budget_cap=…)`` write; M7.5 enforces it)."""
    await conn.execute(
        text("UPDATE campaign_run SET budget_cap_cents = :c, updated_at = now() WHERE id = :id"),
        {"id": campaign_run_id, "c": budget_cap_cents},
    )


async def set_tier_cutoffs(
    conn: AsyncConnection, campaign_run_id: CampaignRunId, tier_cutoffs: TierCutoffs
) -> None:
    """Set the tier cutoffs the tiering phase (M6.4) reads (the ``adjust`` tier-cutoffs write)."""
    await conn.execute(
        text(
            "UPDATE campaign_run SET tier_cutoffs_json = CAST(:c AS jsonb), updated_at = now() "
            "WHERE id = :id"
        ),
        {"id": campaign_run_id, "c": serialize_value_json(tier_cutoffs)},
    )


# --- campaign_phase_checkpoint -------------------------------------------------------------------

_CHECKPOINT_COLUMNS = (
    "id, campaign_run_id, phase, idempotency_key, status, payload_json, committed_at, "
    "created_at, updated_at"
)

# Upsert on the natural (campaign_run_id, phase) key: stage IN_PROGRESS, then COMMIT/AWAIT/FAIL the
# same row. ``committed_at`` is computed in SQL — stamped to ``now()`` exactly when status becomes
# COMMITTED and cleared otherwise — so the DB CHECK (committed_at IS NOT NULL iff committed) can
# never be violated and the caller never has to supply a timestamp.
_UPSERT_CHECKPOINT_SQL = text(
    """
    INSERT INTO campaign_phase_checkpoint (
        id, campaign_run_id, phase, idempotency_key, status, payload_json, committed_at
    )
    VALUES (
        :id, :campaign_run_id, CAST(:phase AS campaign_phase), :idempotency_key,
        CAST(:status AS phase_checkpoint_status), CAST(:payload AS jsonb),
        CASE WHEN :status = 'committed' THEN now() ELSE NULL END
    )
    ON CONFLICT (campaign_run_id, phase) DO UPDATE
    SET status = EXCLUDED.status,
        payload_json = EXCLUDED.payload_json,
        committed_at = CASE WHEN EXCLUDED.status = 'committed' THEN now() ELSE NULL END,
        updated_at = now()
    """
)

_GET_CHECKPOINT_SQL = text(
    f"SELECT {_CHECKPOINT_COLUMNS} FROM campaign_phase_checkpoint "
    "WHERE campaign_run_id = :run AND phase = CAST(:phase AS campaign_phase)"
)


async def upsert_checkpoint(
    conn: AsyncConnection,
    *,
    campaign_run_id: CampaignRunId,
    phase: CampaignPhase,
    idempotency_key: str,
    status: PhaseCheckpointStatus,
    payload: dict[str, JsonValue],
) -> None:
    """Upsert the ``(campaign_run, phase)`` checkpoint to ``status`` with ``payload``.

    The first call for a phase inserts (``IN_PROGRESS``); subsequent calls update the same row to
    ``COMMITTED`` / ``AWAITING_INPUT`` / ``FAILED``. ``committed_at`` is stamped automatically (in
    SQL) iff ``status`` is ``COMMITTED`` — the caller never supplies it."""
    await conn.execute(
        _UPSERT_CHECKPOINT_SQL,
        {
            "id": uuid4(),
            "campaign_run_id": campaign_run_id,
            "phase": phase.value,
            "idempotency_key": idempotency_key,
            "status": status.value,
            "payload": serialize_value_json(payload),
        },
    )


async def get_checkpoint(
    conn: AsyncConnection, campaign_run_id: CampaignRunId, phase: CampaignPhase
) -> CampaignPhaseCheckpointRow | None:
    """Read back the durable checkpoint for ``(campaign_run, phase)`` — the M6↔M7 read-back surface
    (M6.4's tier-checkpoint payload is read from here), or ``None`` if the phase has not run."""
    row = (
        (await conn.execute(_GET_CHECKPOINT_SQL, {"run": campaign_run_id, "phase": phase.value}))
        .mappings()
        .one_or_none()
    )
    return _row_to_checkpoint(dict(row)) if row is not None else None


# --- adjustment_journal --------------------------------------------------------------------------

_INSERT_ADJUSTMENT_SQL = text(
    """
    INSERT INTO adjustment_journal (id, campaign_run_id, kind, detail_json)
    VALUES (:id, :campaign_run_id, :kind, CAST(:detail AS jsonb))
    """
)

_LIST_ADJUSTMENTS_SQL = text(
    "SELECT id, campaign_run_id, kind, detail_json, created_at FROM adjustment_journal "
    "WHERE campaign_run_id = :run ORDER BY seq"
)


async def insert_adjustment(
    conn: AsyncConnection,
    *,
    campaign_run_id: CampaignRunId,
    kind: str,
    detail: dict[str, JsonValue],
) -> None:
    """Append one immutable adjustment record (M7.3) — "adjustments are journaled"."""
    await conn.execute(
        _INSERT_ADJUSTMENT_SQL,
        {
            "id": uuid4(),
            "campaign_run_id": campaign_run_id,
            "kind": kind,
            "detail": serialize_value_json(detail),
        },
    )


async def list_adjustments(
    conn: AsyncConnection, campaign_run_id: CampaignRunId
) -> list[AdjustmentRow]:
    """All adjustments for a run, oldest first (the audit trail)."""
    rows = (await conn.execute(_LIST_ADJUSTMENTS_SQL, {"run": campaign_run_id})).mappings().all()
    return [_row_to_adjustment(dict(r)) for r in rows]


# --- row decoders --------------------------------------------------------------------------------


def _decode_jsonb(raw: object) -> object:
    """Decode a JSONB column to a Python object (asyncpg returns it already decoded)."""
    if isinstance(raw, (bytes, bytearray)):
        return parse_value_json(bytes(raw))
    return raw


def _row_to_campaign_run(row: dict[str, object]) -> CampaignRunRow:
    return CampaignRunRow.model_validate(
        {
            "id": row["id"],
            "client_id": row["client_id"],
            "icp_key": row["icp_key"],
            "icp_version": row["icp_version"],
            "phase": row["phase"],
            "status": row["status"],
            "budget_cap_cents": row["budget_cap_cents"],
            "spent_cents": row["spent_cents"] if row["spent_cents"] is not None else Decimal(0),
            "tier_cutoffs": _decode_jsonb(row["tier_cutoffs_json"]),
            "paused_at": row["paused_at"],
            "resumed_at": row["resumed_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    )


def _row_to_checkpoint(row: dict[str, object]) -> CampaignPhaseCheckpointRow:
    return CampaignPhaseCheckpointRow.model_validate(
        {
            "id": row["id"],
            "campaign_run_id": row["campaign_run_id"],
            "phase": row["phase"],
            "idempotency_key": row["idempotency_key"],
            "status": row["status"],
            "payload": _decode_jsonb(row["payload_json"]),
            "committed_at": row["committed_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    )


def _row_to_adjustment(row: dict[str, object]) -> AdjustmentRow:
    return AdjustmentRow.model_validate(
        {
            "id": row["id"],
            "campaign_run_id": row["campaign_run_id"],
            "kind": row["kind"],
            "detail": _decode_jsonb(row["detail_json"]),
            "created_at": row["created_at"],
        }
    )
