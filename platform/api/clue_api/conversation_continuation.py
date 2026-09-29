"""Where a Head-of-ABM turn continues the thread's conversation from (spec 2026-09-29 §3.1).

A new turn resumes the saved graph state of the thread's latest **completed** Head-of-ABM turn
that ran under the same profile, prompt and tool surface. Everything the thread said after that
turn — a stopped or failed turn's messages, design-leg exchanges, derived turns — is not in that
state, so it is handed to the new turn as *gap* messages, in ``sequence`` order.

No resume point (first turn, changed profile, nothing completed yet) means the turn is assembled
fresh, as before.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import ArtifactRef
from clue_agents.ports import HistoryMessageRef
from clue_api.turn_attachments import turn_image_refs

__all__ = [
    "ResumePoint",
    "continuation_config_for",
    "find_resume_point",
    "gap_history",
    "thread_message_refs",
]


@dataclass(frozen=True)
class ResumePoint:
    """The completed turn whose saved graph state a new turn continues."""

    turn_id: UUID
    execution_id: UUID
    last_message_sequence: int


async def find_resume_point(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    thread_id: str,
    current_turn_id: UUID,
    profile_name: str,
    profile_version: str,
    profile_sha256: str,
    resource_manifest_sha256: str,
) -> ResumePoint | None:
    """The thread's latest finished Head-of-ABM turn under this exact profile, if any.

    Finished = its finalization committed as ``completed`` or ``awaiting_input`` (a chat turn that
    ends on a question to the human — most of them). A stopped, failed, abandoned, erased or
    still-running turn is never a resume point: its state is not a settled conversation, or is no
    longer one we may keep reading. A turn under a different profile, prompt or tool surface is
    not either — its old system prompt is baked into its saved state.
    """
    row = (
        (
            await conn.execute(
                text(
                    "SELECT t.id, t.execution_id, "
                    " (SELECT max(m.sequence) FROM agent_thread_message m "
                    "  WHERE m.workspace_id=t.workspace_id AND m.thread_id=t.thread_id "
                    "  AND m.turn_id=t.id) AS last_sequence "
                    "FROM agent_turn t "
                    "WHERE t.workspace_id=:workspace AND t.thread_id=:thread "
                    "AND t.role='head_of_abm' AND t.id<>:current "
                    "AND t.profile_name=:name AND t.profile_version=:version "
                    "AND t.profile_sha256=:profile_sha "
                    "AND t.resource_manifest_sha256=:manifest_sha "
                    "AND EXISTS (SELECT 1 FROM agent_turn_event e WHERE e.turn_id=t.id "
                    " AND e.workspace_id=t.workspace_id "
                    " AND e.status IN ('completed', 'awaiting_input')) "
                    "AND NOT EXISTS (SELECT 1 FROM agent_turn_event e WHERE e.turn_id=t.id "
                    " AND e.workspace_id=t.workspace_id AND e.status IN "
                    " ('failed', 'cancelled', 'abandoned', 'privacy_tombstoned')) "
                    "AND EXISTS (SELECT 1 FROM agent_thread_message m "
                    " WHERE m.workspace_id=t.workspace_id AND m.thread_id=t.thread_id "
                    " AND m.turn_id=t.id) "
                    "ORDER BY t.requested_at DESC, t.id DESC LIMIT 1"
                ),
                {
                    "workspace": workspace_id,
                    "thread": thread_id,
                    "current": current_turn_id,
                    "name": profile_name,
                    "version": profile_version,
                    "profile_sha": profile_sha256,
                    "manifest_sha": resource_manifest_sha256,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return ResumePoint(
        turn_id=row["id"],
        execution_id=row["execution_id"],
        last_message_sequence=int(row["last_sequence"]),
    )


async def gap_history(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    thread_id: str,
    after_sequence: int,
    current_turn_id: UUID,
) -> tuple[HistoryMessageRef, ...]:
    """The Head of ABM's view of the thread after the resume point, minus the current turn.

    The same role-scoped view a fresh turn's history is (``load_head_of_abm_history``): a design
    leg's transcript never enters, its journaled exit summary does.
    """
    return await thread_message_refs(
        conn,
        workspace_id=workspace_id,
        thread_id=thread_id,
        after_sequence=after_sequence,
        exclude_turn_id=current_turn_id,
        head_of_abm_view=True,
    )


def continuation_config_for(point: ResumePoint) -> dict[str, Any]:
    """The graph config that reads the resume point's saved state.

    A Head-of-ABM turn's graph runs with ``thread_id`` = its execution id; its checkpoints are
    stored under the root namespace (verified 2026-09-29 against stored rows).
    """
    return {"configurable": {"thread_id": str(point.execution_id), "checkpoint_ns": ""}}


async def thread_message_refs(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    thread_id: str,
    after_sequence: int | None = None,
    exclude_turn_id: UUID | None = None,
    head_of_abm_view: bool = False,
) -> tuple[HistoryMessageRef, ...]:
    """A thread's stored messages, in ``sequence`` order, as history references.

    ``head_of_abm_view`` is PD-part3 §2.4's role scope: no design-turn message, except the exit
    summary ``finish_design_leg`` journaled at a leg's close — a summary, never a transcript.
    """
    result = await conn.execute(
        text(
            "SELECT m.id, m.turn_id, m.sequence, m.role, m.body_artifact_key, "
            "m.body_sha256, a.media_type, a.size_bytes, "
            "EXISTS (SELECT 1 FROM agent_turn_event e WHERE e.turn_id=m.turn_id "
            "AND e.workspace_id=m.workspace_id AND e.status='cancelled') AS interrupted "
            "FROM agent_thread_message m "
            "JOIN agent_turn t ON t.id = m.turn_id AND t.workspace_id = m.workspace_id "
            "JOIN artifact a ON a.storage_key=m.body_artifact_key "
            "WHERE m.workspace_id=:workspace AND m.thread_id=:thread "
            "AND (NOT CAST(:scoped AS boolean) OR t.role <> 'design' OR m.id IN ("
            "    SELECT CAST(j.summary_refs->>'summary_message_id' AS uuid) "
            "    FROM design_leg_exit_journal j "
            "    WHERE j.workspace_id = m.workspace_id "
            "      AND j.summary_refs ? 'summary_message_id'"
            ")) "
            "AND (CAST(:after AS bigint) IS NULL OR m.sequence > :after) "
            "AND (CAST(:exclude AS uuid) IS NULL OR m.turn_id <> :exclude) "
            "ORDER BY m.sequence"
        ),
        {
            "workspace": workspace_id,
            "thread": thread_id,
            "after": after_sequence,
            "exclude": exclude_turn_id,
            "scoped": head_of_abm_view,
        },
    )
    rows = result.mappings().all()
    # One query for the whole page, not one per message: the images a past turn carried ride its
    # messages again (ruling 2, spec 2026-09-18), and the conversation layer caps how many of them
    # the thread can afford.
    images = await turn_image_refs(
        conn,
        workspace_id=workspace_id,
        turn_ids=[row["turn_id"] for row in rows],
    )
    return tuple(_history_ref(row, workspace_id, images) for row in rows)


def _history_ref(
    row: Any, workspace_id: str, images: dict[UUID, tuple[ArtifactRef, ...]]
) -> HistoryMessageRef:
    return HistoryMessageRef(
        message_id=row["id"],
        turn_id=row["turn_id"],
        sequence=int(row["sequence"]),
        role=row["role"],
        interrupted=bool(row["interrupted"]),
        body_ref=ArtifactRef(
            workspace_id=workspace_id,
            artifact_key=row["body_artifact_key"],
            sha256=row["body_sha256"],
            media_type=row["media_type"],
            byte_count=int(row["size_bytes"]),
        ),
        attachment_refs=images.get(row["turn_id"], ()),
    )
