"""Design-leg DAL (Part III P3.1) — the durable HITL carrier of PD-part3 §2.1.

Ruling D1: the leg row IS the "interrupted graph". The master plan's HITL node
materializes as the state machine here, and lane-D's ingestion routing rule is one
indexed read (:func:`get_open_leg_for_thread`): an open leg on the thread receives the
user's message; otherwise head-of-abm does.

State machine (enforced by guarded UPDATEs — wrong state raises
:class:`~clue_design.errors.DesignLegStateError`, never a silent no-op):

    open_awaiting_user ──(message dispatched as a design turn)──► running
    running ──(turn ends, leg still open)──► open_awaiting_user
    running | open_awaiting_user ──(finish_design_leg validated)──► closed(reason)
    closed ──(re-delegation names this leg)──► open_awaiting_user      # mis-exit reopen

Invariants owned by the schema (migration ``549de68ae3b9``): at most one non-closed leg
per thread (partial unique index — D4); ``closed ⟺ close_reason`` set; a brand pin is
``(id, version)`` or absent; exit decisions are append-only journal rows that survive
reopens. ``out_of_scope`` requires a ``pending_user_message_ref`` — validated here
eagerly (engine disposes) and by the journal CHECK.

Fail-closed tenancy per the D2 error-taxonomy rule: every read/write keys
``(leg_id, workspace_id)``; another tenant's leg is indistinguishable from a missing one.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from .errors import DesignLegStateError, DesignNotFoundError

JsonObject = dict[str, Any]

_OPEN_STATES = ("open_awaiting_user", "running")

_LEG_COLUMNS = (
    "id, workspace_id, thread_id, parent_execution_id, opened_by_turn_id, state, "
    "bundle_artifact_ref, document_id, document_version_guard, brand_kit_id, "
    "brand_kit_version, close_reason, closed_by_run_id, created_at, updated_at"
)


def _leg_from_row(row: Any) -> JsonObject:
    mapping = dict(row._mapping)
    mapping["id"] = str(mapping["id"])
    mapping["parent_execution_id"] = str(mapping["parent_execution_id"])
    if mapping.get("opened_by_turn_id") is not None:
        mapping["opened_by_turn_id"] = str(mapping["opened_by_turn_id"])
    return mapping


async def open_leg(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    thread_id: str,
    parent_execution_id: Any,
    opened_by_turn_id: Any = None,
    bundle_artifact_ref: str | None = None,
    document_id: str | None = None,
    document_version_guard: int | None = None,
    brand_kit_id: str | None = None,
    brand_kit_version: int | None = None,
    leg_id: str | None = None,
) -> JsonObject:
    """Birth a leg ``open_awaiting_user``. A second open leg on the thread violates the
    partial unique index and raises — the caller resolves the existing leg first."""
    row = (
        await conn.execute(
            text(
                f"""
                INSERT INTO design_leg (
                    id, workspace_id, thread_id, parent_execution_id, opened_by_turn_id,
                    bundle_artifact_ref, document_id, document_version_guard,
                    brand_kit_id, brand_kit_version
                ) VALUES (
                    :id, :ws, :thread, :execution, :turn,
                    :bundle, :document, :version_guard, :brand, :brand_version
                )
                RETURNING {_LEG_COLUMNS}
                """
            ),
            {
                "id": leg_id or str(uuid4()),
                "ws": workspace_id,
                "thread": thread_id,
                "execution": parent_execution_id,
                "turn": opened_by_turn_id,
                "bundle": bundle_artifact_ref,
                "document": document_id,
                "version_guard": document_version_guard,
                "brand": brand_kit_id,
                "brand_version": brand_kit_version,
            },
        )
    ).first()
    assert row is not None  # RETURNING on INSERT
    return _leg_from_row(row)


async def get_leg_closed_by_turn(
    conn: AsyncConnection, *, workspace_id: str, turn_id: Any
) -> JsonObject | None:
    """The leg whose exit journal names this turn as its closer, or ``None``.

    P3.7's crash-window re-entry read: a closing design turn that died between the close and
    its finalization must still route to the design runner on retry — the open-leg lookup
    finds nothing (the leg is closed), so the routing rule falls back to this. Served by the
    ``design_leg_exit_journal_closing_turn`` expression index.
    """

    row = (
        await conn.execute(
            text(
                f"SELECT {_LEG_COLUMNS} FROM design_leg WHERE workspace_id = :ws AND id = ("
                "SELECT j.leg_id FROM design_leg_exit_journal j "
                "WHERE j.workspace_id = :ws "
                "AND j.summary_refs->>'closing_turn_id' = :turn LIMIT 1)"
            ),
            {"ws": workspace_id, "turn": str(turn_id)},
        )
    ).first()
    return _leg_from_row(row) if row is not None else None


async def get_leg(conn: AsyncConnection, *, workspace_id: str, leg_id: str) -> JsonObject:
    row = (
        await conn.execute(
            text(f"SELECT {_LEG_COLUMNS} FROM design_leg WHERE id = :id AND workspace_id = :ws"),
            {"id": leg_id, "ws": workspace_id},
        )
    ).first()
    if row is None:
        raise DesignNotFoundError("design_leg", leg_id)
    return _leg_from_row(row)


async def get_open_leg_for_thread(
    conn: AsyncConnection, *, workspace_id: str, thread_id: str
) -> JsonObject | None:
    """THE routing-rule read (D1): the thread's single non-closed leg, or None."""
    row = (
        await conn.execute(
            text(
                f"SELECT {_LEG_COLUMNS} FROM design_leg "
                "WHERE workspace_id = :ws AND thread_id = :thread AND state <> 'closed'"
            ),
            {"ws": workspace_id, "thread": thread_id},
        )
    ).first()
    return None if row is None else _leg_from_row(row)


async def _transition(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    leg_id: str,
    from_states: tuple[str, ...],
    action: str,
    set_sql: str,
    params: JsonObject | None = None,
) -> None:
    result = await conn.execute(
        text(
            f"UPDATE design_leg SET {set_sql}, updated_at = now() "
            "WHERE id = :id AND workspace_id = :ws AND state IN :from_states"
        ).bindparams(bindparam("from_states", expanding=True)),
        {
            "id": leg_id,
            "ws": workspace_id,
            "from_states": from_states,
            **(params or {}),
        },
    )
    if result.rowcount == 0:
        # Missing and wrong-state are distinguished so a caller bug reads correctly.
        await get_leg(conn, workspace_id=workspace_id, leg_id=leg_id)
        raise DesignLegStateError(leg_id, " or ".join(from_states), action)


async def mark_leg_running(conn: AsyncConnection, *, workspace_id: str, leg_id: str) -> None:
    await _transition(
        conn,
        workspace_id=workspace_id,
        leg_id=leg_id,
        from_states=("open_awaiting_user",),
        action="mark running",
        set_sql="state = 'running'",
    )


async def mark_leg_awaiting_user(conn: AsyncConnection, *, workspace_id: str, leg_id: str) -> None:
    await _transition(
        conn,
        workspace_id=workspace_id,
        leg_id=leg_id,
        from_states=("running",),
        action="mark awaiting user",
        set_sql="state = 'open_awaiting_user'",
    )


async def close_leg(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    leg_id: str,
    reason: str,
    summary_refs: JsonObject,
    pending_user_message_ref: str | None = None,
    decided_by_run_id: str | None = None,
) -> str:
    """The only path to ``closed`` (PD-part3 §2.2). Journals first (append-only), then
    flips the leg. Returns the journal row id."""
    if reason == "out_of_scope" and not pending_user_message_ref:
        raise ValueError(
            "close_leg(reason='out_of_scope') requires pending_user_message_ref — "
            "the engine re-delivers it to head-of-abm on leg close (PD-part3 §2.2)"
        )
    journal_id = str(uuid4())
    await conn.execute(
        text(
            "INSERT INTO design_leg_exit_journal "
            "(id, leg_id, workspace_id, reason, summary_refs, pending_user_message_ref, "
            " decided_by_run_id) "
            "VALUES (:id, :leg, :ws, :reason, CAST(:summary AS jsonb), :pending, :run)"
        ),
        {
            "id": journal_id,
            "leg": leg_id,
            "ws": workspace_id,
            "reason": reason,
            "summary": json.dumps(summary_refs),
            "pending": pending_user_message_ref,
            "run": decided_by_run_id,
        },
    )
    await _transition(
        conn,
        workspace_id=workspace_id,
        leg_id=leg_id,
        from_states=_OPEN_STATES,
        action=f"close ({reason})",
        set_sql="state = 'closed', close_reason = :reason_value, closed_by_run_id = :run_value",
        params={"reason_value": reason, "run_value": decided_by_run_id},
    )
    return journal_id


async def reopen_leg(conn: AsyncConnection, *, workspace_id: str, leg_id: str) -> None:
    """The mis-exit recovery (PD-part3 §2.2): re-delegation reopens the SAME leg —
    history and context resume where they were; the exit journal keeps the record."""
    await _transition(
        conn,
        workspace_id=workspace_id,
        leg_id=leg_id,
        from_states=("closed",),
        action="reopen",
        set_sql="state = 'open_awaiting_user', close_reason = NULL, closed_by_run_id = NULL",
    )


@dataclass(frozen=True, slots=True)
class LegDocumentSpec:
    """One document of a leg: its birth position and the item's own words (spec §3.1)."""

    document_id: str
    position: int
    note: str = ""


async def add_leg_documents(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    leg_id: str,
    documents: Sequence[LegDocumentSpec],
) -> None:
    """Record the leg's document set. Schema-refused on a duplicate position or document."""
    for spec in documents:
        await conn.execute(
            text(
                "INSERT INTO design_leg_document "
                "(leg_id, workspace_id, document_id, position, note) "
                "VALUES (:leg, :ws, :doc, :pos, :note)"
            ),
            {
                "leg": leg_id,
                "ws": workspace_id,
                "doc": spec.document_id,
                "pos": spec.position,
                "note": spec.note,
            },
        )


async def list_leg_documents(
    conn: AsyncConnection, *, workspace_id: str, leg_id: str
) -> list[JsonObject]:
    """The leg's documents in position order, each with the document facts the runner, the
    judge and the composer need. Fail-closed on workspace at both rows."""
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT ld.document_id, ld.position, ld.note, d.title, d.doc_kind, "
                    "d.current_version, d.account_id "
                    "FROM design_leg_document ld "
                    "JOIN design_document d "
                    "  ON d.id = ld.document_id AND d.workspace_id = ld.workspace_id "
                    "WHERE ld.leg_id = :leg AND ld.workspace_id = :ws "
                    "ORDER BY ld.position ASC"
                ),
                {"leg": leg_id, "ws": workspace_id},
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]
