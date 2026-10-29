"""Comments go to the page they were left on (2026-10-29, founder ruling: the server routes them).

A person can leave comments on any site or web page of the project from its comment box and send
them, whatever the chat has open: no design session, or one on another page or ad. Comments are
``design_node`` refs that carry a ``note`` (a canvas selection on an ad carries none), beside one
``design_document`` ref naming the page.

The chat router accepts such a message even when the page is not on the open leg; this module is
the turn worker's half. Before the worker routes the turn it calls
:func:`move_leg_to_commented_document`, which — in the worker's transaction, so the move and the
turn that rides it commit or fail together — makes the page's leg the thread's open leg:

1. a leg open on the thread that does not hold the page is closed (``abandoned``; its journal
   names the page it moved to and never a ``closing_turn_id``, so the crash re-entry read cannot
   mistake this turn for the leg's own closer);
2. this chat's own latest leg for the page is reopened (its brief, history and pins resume), or,
   when the page was made in another chat of the project, a leg is opened here that copies the
   page's latest leg: its frozen brief, brand pin, parent execution and the page's own note.

No model is asked. Each transition is announced on the turn's stream as the open/finish tools
announce theirs (``leg.closed`` with its reason, then ``leg.opened``/``leg.reopened``), so the
chat shows the session changing; the opening frames also carry ``leg_turn: true``, because unlike
the tool's they ride the leg's own design turn. A retried turn finds the page already on the open
leg and moves nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import DomainObjectRef
from clue_api.chat.turn_events import TurnEventType, emit_turn_event
from clue_design import legs as design_legs
from clue_design.documents import get_document

__all__ = ["commented_document_id", "move_leg_to_commented_document"]

#: The close reason a moved-away leg records (the schema's own vocabulary has no other fit: the
#: person did not lock the page in, and nothing is re-delivered to the Head of ABM).
MOVED_AWAY_CLOSE_REASON = "abandoned"


def commented_document_id(refs: Sequence[DomainObjectRef]) -> str | None:
    """The page a message's comments were left on, or ``None`` when it carries no comments.

    Comments are ``design_node`` refs with a note; the composer sends them with exactly one
    ``design_document`` ref, the page itself (the submission check refuses anything else).
    """

    if not any(ref.object_type == "design_node" and (ref.note or "").strip() for ref in refs):
        return None
    documents = [ref.object_id for ref in refs if ref.object_type == "design_document"]
    return str(documents[0]) if len(documents) == 1 else None


async def _leg_document_ids(
    conn: AsyncConnection, *, workspace_id: str, leg: dict[str, Any]
) -> set[str]:
    documents = {
        str(row["document_id"])
        for row in await design_legs.list_leg_documents(
            conn, workspace_id=workspace_id, leg_id=str(leg["id"])
        )
    }
    # A leg born before the document set was recorded still names its own pin.
    if not documents and leg.get("document_id"):
        documents.add(str(leg["document_id"]))
    return documents


async def _latest_leg_for_document(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    document_id: str,
    thread_id: str | None,
) -> dict[str, Any] | None:
    """The latest leg naming ``document_id`` — on ``thread_id`` when given, else on any thread
    of the project (a page belongs to a project only through the legs that name it)."""

    row = (
        await conn.execute(
            text(
                "SELECT l.id FROM design_leg l "
                "JOIN agent_thread t ON t.id = l.thread_id AND t.workspace_id = l.workspace_id "
                "WHERE l.workspace_id = :ws AND t.project_id = :project "
                "AND (CAST(:thread AS text) IS NULL OR l.thread_id = :thread) "
                "AND (l.document_id = :doc OR EXISTS ("
                "  SELECT 1 FROM design_leg_document ld "
                "  WHERE ld.leg_id = l.id AND ld.workspace_id = l.workspace_id "
                "  AND ld.document_id = :doc)) "
                "ORDER BY l.updated_at DESC, l.created_at DESC, l.id DESC LIMIT 1"
            ),
            {"ws": workspace_id, "project": project_id, "thread": thread_id, "doc": document_id},
        )
    ).first()
    if row is None:
        return None
    return await design_legs.get_leg(conn, workspace_id=workspace_id, leg_id=str(row[0]))


async def _announce(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    thread_id: str,
    turn_id: UUID,
    event_type: TurnEventType,
    leg_id: str,
    reason: str | None = None,
) -> None:
    payload: dict[str, Any] = {"leg_id": leg_id}
    if reason is not None:
        payload["reason"] = reason
    if event_type is not TurnEventType.LEG_CLOSED:
        # This turn is the leg's own design turn, not a Head of ABM turn that opened it: the
        # chat shows it designing (the open tool's frames, on the opener's turn, carry no flag).
        payload["leg_turn"] = True
    await emit_turn_event(
        conn,
        workspace_id=workspace_id,
        project_id=project_id,
        thread_id=thread_id,
        turn_id=turn_id,
        event_type=event_type,
        payload=payload,
    )


async def move_leg_to_commented_document(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    thread_id: str,
    turn_id: UUID,
    focus_refs: Sequence[DomainObjectRef],
    open_leg: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Make the commented page's leg the thread's open leg, and return it.

    ``None`` when nothing moves: the message carries no comments, or the open leg already holds
    the page. The caller runs the turn on the returned leg.
    """

    document_id = commented_document_id(focus_refs)
    if document_id is None:
        return None
    if open_leg is not None and document_id in await _leg_document_ids(
        conn, workspace_id=workspace_id, leg=open_leg
    ):
        return None

    # The page as it stands now — the version the new leg guards and the comments were checked at.
    document = await get_document(conn, workspace_id=workspace_id, document_id=document_id)

    if open_leg is not None:
        leg_id = str(open_leg["id"])
        await design_legs.close_leg(
            conn,
            workspace_id=workspace_id,
            leg_id=leg_id,
            reason=MOVED_AWAY_CLOSE_REASON,
            summary_refs={"moved_to_document_id": document_id, "moved_by_turn_id": str(turn_id)},
        )
        await _announce(
            conn,
            workspace_id=workspace_id,
            project_id=project_id,
            thread_id=thread_id,
            turn_id=turn_id,
            event_type=TurnEventType.LEG_CLOSED,
            leg_id=leg_id,
            reason=MOVED_AWAY_CLOSE_REASON,
        )

    own = await _latest_leg_for_document(
        conn,
        workspace_id=workspace_id,
        project_id=project_id,
        document_id=document_id,
        thread_id=thread_id,
    )
    if own is not None:
        # Closed by construction: the thread's one open leg (if any) did not hold the page and
        # was closed just above.
        await design_legs.reopen_leg(conn, workspace_id=workspace_id, leg_id=str(own["id"]))
        await _announce(
            conn,
            workspace_id=workspace_id,
            project_id=project_id,
            thread_id=thread_id,
            turn_id=turn_id,
            event_type=TurnEventType.LEG_REOPENED,
            leg_id=str(own["id"]),
        )
        return await design_legs.get_leg(conn, workspace_id=workspace_id, leg_id=str(own["id"]))

    source = await _latest_leg_for_document(
        conn,
        workspace_id=workspace_id,
        project_id=project_id,
        document_id=document_id,
        thread_id=None,
    )
    if source is None:
        # The submission check only admits a page of this project, and a page belongs to a
        # project only through a leg that names it — so this is a broken invariant, not a case.
        raise LookupError(f"design document {document_id} has no design leg in this project")
    source_note = next(
        (
            str(row.get("note") or "")
            for row in await design_legs.list_leg_documents(
                conn, workspace_id=workspace_id, leg_id=str(source["id"])
            )
            if str(row["document_id"]) == document_id
        ),
        "",
    )
    new_leg_id = str(uuid5(NAMESPACE_URL, f"clue:design-comment-leg:{workspace_id}:{turn_id}"))
    leg = await design_legs.open_leg(
        conn,
        workspace_id=workspace_id,
        thread_id=thread_id,
        parent_execution_id=source["parent_execution_id"],
        # Not the opener: this turn is the leg's own first design turn, and the routing rule
        # sends the turn that opened a leg to the Head of ABM.
        opened_by_turn_id=None,
        bundle_artifact_ref=source.get("bundle_artifact_ref"),
        document_id=document_id,
        document_version_guard=int(document.get("current_version") or 0),
        brand_kit_id=source.get("brand_kit_id"),
        brand_kit_version=source.get("brand_kit_version"),
        leg_id=new_leg_id,
    )
    await design_legs.add_leg_documents(
        conn,
        workspace_id=workspace_id,
        leg_id=new_leg_id,
        documents=[
            design_legs.LegDocumentSpec(document_id=document_id, position=0, note=source_note)
        ],
    )
    await _announce(
        conn,
        workspace_id=workspace_id,
        project_id=project_id,
        thread_id=thread_id,
        turn_id=turn_id,
        event_type=TurnEventType.LEG_OPENED,
        leg_id=new_leg_id,
    )
    return leg
