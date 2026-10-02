"""Persist an interrupted answer before publishing terminal cancellation."""

from uuid import UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import ArtifactRef
from clue_agents.turns import AgentTurnStatus
from clue_api.agent_turn_submission import lock_thread_queue
from clue_api.agent_turn_wiring import DbAgentHistoryStore, _append_turn_event
from clue_api.chat.queue_controls import clear_empty_hold
from clue_api.chat.turn_controls import lock_turn_control, stop_requested


async def recover_interrupted_answer(
    conn: AsyncConnection, *, workspace_id: str, turn_id: UUID
) -> str:
    """After a worker crash, recover the last answer part, never reasoning or reset parts."""
    return str(
        await conn.scalar(
            text("""
        WITH latest AS (
            SELECT part_id FROM agent_turn_event_stream
            WHERE workspace_id=:workspace AND turn_id=:turn
              AND event_type='text.start' AND part_kind='text'
            ORDER BY event_id DESC LIMIT 1
        )
        SELECT COALESCE(string_agg(e.payload->>'delta', '' ORDER BY e.event_id), '')
        FROM agent_turn_event_stream e JOIN latest l ON l.part_id=e.part_id
        WHERE e.workspace_id=:workspace AND e.turn_id=:turn AND e.event_type='text.delta'
          AND e.part_kind='text' AND NOT EXISTS (
            SELECT 1 FROM agent_turn_event_stream r WHERE r.workspace_id=e.workspace_id
              AND r.turn_id=e.turn_id AND r.part_id=e.part_id AND r.event_type='part.reset')
    """),
            {"workspace": workspace_id, "turn": turn_id},
        )
        or ""
    )


async def commit_interrupted_turn(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    thread_id: str,
    turn_id: UUID,
    body_ref: ArtifactRef | None,
) -> None:
    await lock_thread_queue(conn, workspace_id=workspace_id, thread_id=thread_id)
    await lock_turn_control(conn, workspace_id=workspace_id, turn_id=turn_id)
    if not await stop_requested(conn, workspace_id=workspace_id, turn_id=turn_id):
        raise ValueError("interrupted history requires a durable Stop")
    if await conn.scalar(
        text(
            "SELECT 1 FROM agent_finalization_commit WHERE "
            "workspace_id=:workspace AND turn_id=:turn"
        ),
        {"workspace": workspace_id, "turn": turn_id},
    ):
        raise ValueError("a committed finalization cannot be replaced by interrupted history")
    if body_ref is not None:
        await DbAgentHistoryStore.append_in_transaction(
            conn,
            message_id=uuid5(turn_id, "assistant"),
            turn_id=turn_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            role="assistant",
            body_ref=body_ref,
        )
    if await conn.scalar(
        text("SELECT 1 FROM agent_turn WHERE id=:turn AND workspace_id=:workspace"),
        {"turn": turn_id, "workspace": workspace_id},
    ):
        await _append_turn_event(
            conn,
            turn_id=turn_id,
            workspace_id=workspace_id,
            status=AgentTurnStatus.CANCELLED,
            reason_code="stop_requested",
        )
    # A Stop can arrive after fleet claim but before an agent_turn is created.
    # Its acknowledgement belongs to the existing submission/control, with no fake execution.
    await conn.execute(
        text(
            "INSERT INTO agent_turn_stop_ack (control_id) SELECT "
            "control_id FROM agent_turn_control_request "
            "WHERE workspace_id=:workspace AND turn_id=:turn AND kind='stop' ON CONFLICT DO NOTHING"
        ),
        {"workspace": workspace_id, "turn": turn_id},
    )
    await clear_empty_hold(conn, workspace_id=workspace_id, thread_id=thread_id, turn_id=turn_id)
