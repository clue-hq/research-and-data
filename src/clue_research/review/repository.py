"""DB access for the M13.1 review tables (``review_session`` + ``review_action``).

The thin persistence layer behind :class:`~clue_research.review.surface.ReviewSurfaceImpl` — keeps
the SQL in one place; the surface owns the orchestration. ``review_session`` is a *mutable* cursor
(the ``open``→``finalized`` transition), so it is UPDATEd; ``review_action`` is the *append-only*
audit (guarded by the DB reject trigger), so this module only ever INSERTs into it.

``review`` may import ``core``/``config``/``obs`` + the M1-M4 services (``claimstore``/``identity``/
``icp``/``sources``); this module needs only ``core`` + ``db`` (the connection is passed in, the
claim-store seam style — no business SQL in ``db/``).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.core import (
    CampaignRunId,
    ClaimId,
    EntityId,
    ReviewAction,
    ReviewRejectReason,
    ReviewSessionStatus,
    UtcDatetime,
    serialize_value_json,
)
from clue_research.core.review import ReviewSessionId

_SESSION_COLS = (
    "id, account_entity_id, campaign_run_id, client_id, review_round, "
    "status, opened_by, opened_at, finalized_at"
)


class ReviewSessionRow(BaseModel):
    """One ``review_session`` row (M13.1) — the cursor over one account_handoff candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: ReviewSessionId
    account_entity_id: EntityId
    campaign_run_id: CampaignRunId
    client_id: str
    review_round: int
    status: ReviewSessionStatus
    opened_by: str | None
    opened_at: UtcDatetime
    finalized_at: UtcDatetime | None


def _to_session(row: Row[Any]) -> ReviewSessionRow:
    m = row._mapping
    return ReviewSessionRow(
        id=ReviewSessionId(m["id"]),
        account_entity_id=EntityId(m["account_entity_id"]),
        campaign_run_id=CampaignRunId(m["campaign_run_id"]),
        client_id=m["client_id"],
        review_round=m["review_round"],
        status=ReviewSessionStatus(m["status"]),
        opened_by=m["opened_by"],
        opened_at=m["opened_at"],
        finalized_at=m["finalized_at"],
    )


async def ensure_review_session(
    conn: AsyncConnection,
    *,
    account_entity_id: EntityId,
    campaign_run_id: CampaignRunId,
    client_id: str,
    review_round: int = 1,
    opened_by: str | None = None,
) -> ReviewSessionRow:
    """Idempotently open a session for ``(account, campaign_run, review_round)`` and return it.

    Idempotent on the UNIQUE scope: a second call returns the existing row unchanged — so the REVIEW
    phase handler re-opening on resume, and the UI re-reading the same candidate, never create a
    duplicate (M13.1 AC: resume never double-advances)."""
    await conn.execute(
        text(
            "INSERT INTO review_session "
            "(id, account_entity_id, campaign_run_id, client_id, review_round, status, opened_by) "
            "VALUES (:id, :acct, :run, :client, :round, 'open', :opened_by) "
            "ON CONFLICT (account_entity_id, campaign_run_id, review_round) DO NOTHING"
        ),
        {
            "id": uuid4(),
            "acct": account_entity_id,
            "run": campaign_run_id,
            "client": client_id,
            "round": review_round,
            "opened_by": opened_by,
        },
    )
    row = (
        await conn.execute(
            text(
                f"SELECT {_SESSION_COLS} FROM review_session WHERE account_entity_id = :acct "
                "AND campaign_run_id = :run AND review_round = :round"
            ),
            {"acct": account_entity_id, "run": campaign_run_id, "round": review_round},
        )
    ).one()
    return _to_session(row)


async def get_review_session(
    conn: AsyncConnection, session_id: ReviewSessionId
) -> ReviewSessionRow | None:
    """The session row, or ``None`` if it does not exist."""
    row = (
        await conn.execute(
            text(f"SELECT {_SESSION_COLS} FROM review_session WHERE id = :id"),
            {"id": session_id},
        )
    ).one_or_none()
    return _to_session(row) if row is not None else None


async def finalize_review_session(
    conn: AsyncConnection, session_id: ReviewSessionId
) -> tuple[ReviewSessionRow | None, bool]:
    """Mark an OPEN session FINALIZED. Returns ``(row, transitioned)``.

    Idempotent: finalizing an already-finalized session returns ``(row, False)`` (no re-transition,
    so the caller does not re-fire the campaign resume). ``(None, False)`` if no such session."""
    row = (
        await conn.execute(
            text(
                "UPDATE review_session SET status = 'finalized', finalized_at = now(), "
                f"updated_at = now() WHERE id = :id AND status = 'open' RETURNING {_SESSION_COLS}"
            ),
            {"id": session_id},
        )
    ).one_or_none()
    if row is not None:
        return _to_session(row), True
    return await get_review_session(conn, session_id), False


async def count_open_sessions(conn: AsyncConnection, campaign_run_id: CampaignRunId) -> int:
    """How many sessions for this run are still OPEN — the resume gate (0 ⇒ review complete)."""
    count = (
        await conn.execute(
            text(
                "SELECT count(*) FROM review_session "
                "WHERE campaign_run_id = :run AND status = 'open'"
            ),
            {"run": campaign_run_id},
        )
    ).scalar_one()
    return int(count)


async def record_review_action(
    conn: AsyncConnection,
    *,
    review_session_id: ReviewSessionId,
    claim_id: ClaimId,
    action: ReviewAction,
    actor: str,
    reason_code: ReviewRejectReason | None = None,
    corrected_value_json: JsonValue | None = None,
    note: str | None = None,
    superseding_claim_id: ClaimId | None = None,
) -> UUID:
    """Append one ``review_action`` audit row; returns its id (append-only — never UPDATEd).

    The DB CHECKs enforce the shape (``correct`` ⟺ corrected value; ``reject`` ⟺ reason; a
    superseding claim ⟺ correct/reject), so the caller passes them consistently with ``action``."""
    action_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO review_action "
            "(id, review_session_id, claim_id, action, reason_code, corrected_value_json, note, "
            " superseding_claim_id, actor) "
            "VALUES (:id, :session, :claim, CAST(:action AS review_action_kind), "
            " CAST(:reason AS review_reject_reason), CAST(:corrected AS jsonb), :note, "
            " :supersede, :actor)"
        ),
        {
            "id": action_id,
            "session": review_session_id,
            "claim": claim_id,
            "action": action.value,
            "reason": reason_code.value if reason_code is not None else None,
            "corrected": (
                serialize_value_json(corrected_value_json)
                if corrected_value_json is not None
                else None
            ),
            "note": note,
            "supersede": superseding_claim_id,
            "actor": actor,
        },
    )
    return action_id
