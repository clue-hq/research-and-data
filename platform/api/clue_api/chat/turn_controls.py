"""Durable stop/retry requests — the write side of charter §3.5's user controls.

FI Lane D slice **D3**. A control is an *act of authority by a human*, so it is recorded exactly
the way this platform records every other one: an immutable, insert-once row carrying the
Clue-owned internal identity of whoever performed it. Nothing here mutates a status column, and
nothing here cancels anything by itself.

**Stop** is a request the worker observes, not an interrupt the HTTP process performs. The web
process has no handle on the running generation — by ratified §6-D1 it does not even compose the
model plane — so the only honest mechanism is a durable row plus a bounded observation interval in
the worker. Its consequences are deliberately narrow (§3.5): it cancels *the active generation
attempt* of one turn. It does not roll back tool effects that already committed (they are durable
receipts of things that happened), and it does not suspend a detached research run (that is the
supervisor tool's job and has its own task state).

**Retry** is a new turn, not a rewritten one. The prior transcript is immutable; a retry records
which turn it retries (``retry_turn_id`` on the control row) and the new turn goes through exactly
the same capture-then-enqueue path a typed message does.

Insert-once by derived id: ``control_id = uuid5(turn_id, kind)``. A double-clicked Stop lands on
the same row and is a replay, not a second cancellation; a second Retry of the same turn resolves
to the retry that already exists rather than forking the conversation.
"""

from __future__ import annotations

from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import UtcDatetime


class TurnStopRequested(RuntimeError):
    """A durable Stop won the race with normal finalization."""


async def lock_turn_control(conn: AsyncConnection, *, workspace_id: str, turn_id: UUID) -> None:
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
        {"scope": f"agent-turn-control:{workspace_id}:{turn_id}"},
    )


__all__ = [
    "TurnControlKind",
    "TurnControlRow",
    "control_id_for",
    "get_control_request",
    "insert_control_request",
    "stop_requested",
]

#: The closed control vocabulary, mirrored by a SQL CHECK (migration ``98a5ddafa21b``).
TurnControlKind = str

_COLUMNS = (
    "control_id, workspace_id, project_id, thread_id, turn_id, kind, target_attempt_id, "
    "retry_turn_id, requested_by_user_id, requested_via_membership_id, requested_at"
)


class TurnControlRow(BaseModel):
    """One immutable control request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    control_id: UUID
    workspace_id: str
    project_id: str
    thread_id: str
    turn_id: UUID
    kind: str
    target_attempt_id: UUID | None
    retry_turn_id: UUID | None
    requested_by_user_id: str
    requested_via_membership_id: str
    requested_at: UtcDatetime


def control_id_for(*, turn_id: UUID, kind: str) -> UUID:
    """The derived id of one control on one turn — the insert-once key."""

    return uuid5(turn_id, f"turn-control:{kind}")


async def insert_control_request(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    thread_id: str,
    turn_id: UUID,
    kind: str,
    requested_by_user_id: str,
    requested_via_membership_id: str,
    target_attempt_id: UUID | None = None,
    retry_turn_id: UUID | None = None,
) -> tuple[TurnControlRow, bool]:
    """Record one control, or replay it. Returns ``(row, created)``.

    A repeated request under the same ``(turn, kind)`` conflicts on the derived primary key and
    reads back the row it conflicted with, so the caller can answer honestly ("already requested")
    instead of pretending to have performed a second cancellation.
    """

    inserted = (
        (
            await conn.execute(
                text(
                    "INSERT INTO agent_turn_control_request "
                    "(control_id, workspace_id, project_id, thread_id, turn_id, kind, "
                    " target_attempt_id, retry_turn_id, requested_by_user_id, "
                    " requested_via_membership_id) "
                    "VALUES (:control_id, :workspace_id, :project_id, :thread_id, :turn_id, "
                    " :kind, :attempt_id, :retry_turn_id, :user_id, :membership_id) "
                    f"ON CONFLICT (control_id) DO NOTHING RETURNING {_COLUMNS}"
                ),
                {
                    "control_id": control_id_for(turn_id=turn_id, kind=kind),
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "thread_id": thread_id,
                    "turn_id": turn_id,
                    "kind": kind,
                    "attempt_id": target_attempt_id,
                    "retry_turn_id": retry_turn_id,
                    "user_id": requested_by_user_id,
                    "membership_id": requested_via_membership_id,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if inserted is not None:
        return TurnControlRow.model_validate(dict(inserted)), True
    existing = await get_control_request(
        conn, workspace_id=workspace_id, turn_id=turn_id, kind=kind
    )
    if existing is None:
        # The derived id exists in another tenant. Deriving from the turn (itself workspace-scoped)
        # makes this practically unreachable; refusing beats confirming another tenant holds it.
        raise LookupError("this control identity exists outside the requested workspace")
    return existing, False


async def get_control_request(
    conn: AsyncConnection, *, workspace_id: str, turn_id: UUID, kind: str
) -> TurnControlRow | None:
    """Read one control **inside one workspace**; a cross-workspace read is a miss."""

    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_COLUMNS} FROM agent_turn_control_request "
                    "WHERE control_id = :control_id AND workspace_id = :workspace_id"
                ),
                {
                    "control_id": control_id_for(turn_id=turn_id, kind=kind),
                    "workspace_id": workspace_id,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    return TurnControlRow.model_validate(dict(row)) if row is not None else None


async def stop_requested(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    turn_id: UUID,
    generation_attempt_id: UUID | None = None,
) -> bool:
    """Whether this turn's active generation attempt has been asked to stop.

    A stop with no ``target_attempt_id`` means "whatever is running now" (the common case — a user
    presses Stop, they do not name a generation). A stop that *does* name an attempt applies only
    to that one, so a stop of a crashed attempt cannot silently kill the retry that replaced it.
    """

    row = await get_control_request(conn, workspace_id=workspace_id, turn_id=turn_id, kind="stop")
    if row is None:
        return False
    if row.target_attempt_id is None or generation_attempt_id is None:
        return True
    return row.target_attempt_id == generation_attempt_id
