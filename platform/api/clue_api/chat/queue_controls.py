"""Thread-scoped queue holds and idempotent human Resume receipts."""

from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_submission import dispatch_next_thread_turn, lock_thread_queue
from clue_projections.threads import thread_turn


class QueueResumeConflict(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


async def queue_control(
    conn: AsyncConnection, *, workspace_id: str, thread_id: str
) -> dict[str, JsonValue]:
    row = (
        (
            await conn.execute(
                text(
                    "SELECT t.queue_hold_control_id, c.requested_at FROM agent_thread t "
                    "LEFT JOIN agent_turn_control_request c ON "
                    "c.control_id=t.queue_hold_control_id "
                    "AND c.workspace_id=t.workspace_id AND c.thread_id=t.id "
                    "WHERE t.workspace_id=:workspace AND t.id=:thread"
                ),
                {"workspace": workspace_id, "thread": thread_id},
            )
        )
        .mappings()
        .one()
    )
    hold = row["queue_hold_control_id"]
    return {
        "paused": hold is not None,
        "hold_control_id": str(hold) if hold else None,
        "paused_at": row["requested_at"].isoformat() if row["requested_at"] else None,
    }


async def hold_queue(
    conn: AsyncConnection, *, workspace_id: str, thread_id: str, control_id: UUID
) -> None:
    # Caller holds the dispatch lock and has accepted a new Stop, not a replay.
    await conn.execute(
        text(
            "UPDATE agent_thread SET queue_hold_control_id=:control "
            "WHERE workspace_id=:workspace AND id=:thread"
        ),
        {"workspace": workspace_id, "thread": thread_id, "control": control_id},
    )


async def clear_empty_hold(
    conn: AsyncConnection, *, workspace_id: str, thread_id: str, turn_id: UUID
) -> None:
    await lock_thread_queue(conn, workspace_id=workspace_id, thread_id=thread_id)
    await conn.execute(
        text("""
        UPDATE agent_thread t SET queue_hold_control_id=NULL
        FROM agent_turn_control_request c
        WHERE t.workspace_id=:workspace AND t.id=:thread
          AND c.control_id=t.queue_hold_control_id AND c.turn_id=:turn
          AND NOT EXISTS (
            SELECT 1 FROM agent_turn_submission s
            WHERE s.workspace_id=t.workspace_id AND s.thread_id=t.id AND s.turn_id<>:turn
              AND s.agent_reply='expected'
              AND NOT EXISTS (SELECT 1 FROM fleet_task f WHERE f.kind='agent_turn'
                AND f.dedup_key='agent-turn:' || s.turn_id::text AND f.status IN ('done','failed'))
          )
    """),
        {"workspace": workspace_id, "thread": thread_id, "turn": turn_id},
    )


async def resume_queue(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    thread_id: str,
    hold_control_id: UUID,
    user_id: str,
    membership_id: str,
) -> dict[str, JsonValue]:
    await lock_thread_queue(conn, workspace_id=workspace_id, thread_id=thread_id)
    params = {"workspace": workspace_id, "thread": thread_id, "hold": hold_control_id}
    control = (
        (
            await conn.execute(
                text(
                    "SELECT turn_id FROM agent_turn_control_request WHERE control_id=:hold "
                    "AND workspace_id=:workspace AND thread_id=:thread AND kind='stop'"
                ),
                params,
            )
        )
        .mappings()
        .one_or_none()
    )
    if control is None:
        raise QueueResumeConflict("QUEUE_HOLD_NOT_FOUND", "this queue hold does not exist")
    state = await queue_control(conn, workspace_id=workspace_id, thread_id=thread_id)
    # A stale replay must never release a newer Stop.
    if state["hold_control_id"] not in (None, str(hold_control_id)):
        raise QueueResumeConflict(
            "QUEUE_HOLD_CHANGED", "the queue has a newer hold; refresh and resume again"
        )
    replayed = bool(
        await conn.scalar(
            text(
                "SELECT 1 FROM agent_thread_queue_resume WHERE hold_control_id=:hold "
                "AND workspace_id=:workspace AND thread_id=:thread"
            ),
            params,
        )
    )
    target = await thread_turn(
        conn, workspace_id=workspace_id, thread_id=thread_id, turn_id=control["turn_id"]
    )
    if target is None or target.state != "cancelled":
        raise QueueResumeConflict(
            "STOP_PENDING", "the current response has not finished cancelling"
        )
    if not replayed:
        await conn.execute(
            text(
                "INSERT INTO agent_thread_queue_resume (hold_control_id,workspace_id,thread_id,"
                "resumed_by_user_id,resumed_via_membership_id) VALUES "
                "(:hold,:workspace,:thread,:user,:membership)"
            ),
            {**params, "user": user_id, "membership": membership_id},
        )
        await conn.execute(
            text(
                "UPDATE agent_thread SET queue_hold_control_id=NULL WHERE workspace_id=:workspace "
                "AND id=:thread AND queue_hold_control_id=:hold"
            ),
            params,
        )
    dispatched = await dispatch_next_thread_turn(
        conn, workspace_id=workspace_id, thread_id=thread_id
    )
    return {
        "hold_control_id": str(hold_control_id),
        "replayed": replayed,
        "dispatched_turn_id": str(dispatched) if dispatched else None,
        "queue_control": await queue_control(conn, workspace_id=workspace_id, thread_id=thread_id),
    }
