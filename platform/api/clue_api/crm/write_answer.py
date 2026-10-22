"""Answering a CRM write permission card, and reading its progress (CRM integration Phase 2, T7).

Spec: docs/superpowers/specs/crm-integration/2026-10-22-crm-write-permission-card-design.md
(§3 states, §6 what the card receives); rulings R-6.5 (an overwrite always asks, so its scope is
never granted from the card), R-6.8 (any workspace member answers and grants "Always allow").

The card is a ``crm_write_permission`` gate answered through the chat's turn route. This module
holds that answer's CRM half:

* :func:`check_answer` proves an answer may be applied, before anything is written: the proposal
  still waits for this card (a newer card ``replaced`` it → ``GATE_REPLACED``), its connection is
  still the workspace's (a reconnect → ``CRM_CONNECTION_CHANGED``), every ticked change belongs to
  the proposal, an approval ticks something, and every "Always allow" was offered by the card;
* :func:`answer_summary` is the one sentence the agent reads in the answering turn;
* :func:`apply_answer` records it, in the answer's own transaction: Allow ticks the chosen changes,
  grants each "Always allow" on the proposal's connection, queues the proposal and offers the
  connection's write executor; Don't allow declines the whole proposal — the changes a standing
  permission covered included — and nothing is sent;
* :func:`proposal_progress` is what ``GET /crm/proposals/{id}`` serves the card. A card a newer card
  replaced reads ``replaced``; one a reconnect closed before anybody answered reads ``closed``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_gate import AgentGateRow
from clue_api.crm.connections import get_connection, latest_connection
from clue_api.crm.write_tools import crm_write_dedup_key
from clue_api.crm.writes import WriteProposal, insert_grant, set_proposal_status
from clue_core import ProjectRunId
from clue_fleet import FleetTaskKind, enqueue_task

__all__ = [
    "CrmAnswerRefused",
    "answer_summary",
    "apply_answer",
    "check_answer",
    "proposal_progress",
]

#: The card's state for each proposal status (card spec §6).
_CARD_STATE = {
    "prepared": "asking",
    "awaiting_permission": "asking",
    "queued": "sending",
    "sending": "sending",
    "paused": "paused",
    "finished": "done",
    "declined": "declined",
    "replaced": "replaced",
}


class CrmAnswerRefused(Exception):
    """The answer cannot be applied; nothing was written."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class _Choices:
    decision: str
    selected_write_ids: tuple[UUID, ...]
    always_allow: tuple[str, ...]


def _choices(decision: str, selected: list[UUID] | None, always: list[str] | None) -> _Choices:
    """The answer's choices, each repeated one collapsed, in the order made."""
    return _Choices(
        decision=decision,
        selected_write_ids=tuple(dict.fromkeys(selected or ())),
        always_allow=tuple(dict.fromkeys(scope.strip() for scope in always or ())),
    )


async def _proposal_for_gate(
    conn: AsyncConnection, gate: AgentGateRow, *, lock: bool = False
) -> WriteProposal | None:
    row = (
        await conn.execute(
            text(
                "SELECT proposal_id, workspace_id, connection_id, project_id, thread_id, turn_id, "
                "status FROM crm_write_proposal WHERE gate_id = :gate AND workspace_id = :ws"
                + (" FOR UPDATE" if lock else "")
            ),
            {"gate": gate.gate_id, "ws": gate.workspace_id},
        )
    ).first()
    return None if row is None else WriteProposal(**dict(row._mapping))


def _offered_scopes(gate: AgentGateRow) -> set[str]:
    """The "Always allow" scopes the card offered: those of its groups, never an overwrite's."""
    offered = gate.subject_snapshot.get("standing_permissions")
    if not isinstance(offered, list):
        return set()
    return {
        str(item["scope_key"])
        for item in offered
        if isinstance(item, dict) and isinstance(item.get("scope_key"), str)
    }


async def check_answer(
    conn: AsyncConnection,
    gate: AgentGateRow,
    *,
    decision: str,
    selected_write_ids: list[UUID] | None,
    always_allow: list[str] | None,
) -> None:
    """Prove this answer may be applied to the card's proposal, or raise :class:`CrmAnswerRefused`.

    Runs only for a first answer (a retried click of the same turn replays without it)."""
    choices = _choices(decision, selected_write_ids, always_allow)
    proposal = await _proposal_for_gate(conn, gate, lock=True)
    if proposal is None:
        raise CrmAnswerRefused(409, "GATE_SUBJECT_STALE", "this card has no proposal behind it")
    if proposal.status == "replaced":
        raise CrmAnswerRefused(409, "GATE_REPLACED", "a newer card replaced this one")
    if proposal.status != "awaiting_permission":
        raise CrmAnswerRefused(409, "GATE_SUBJECT_STALE", "this card is no longer waiting")
    current = await latest_connection(conn, workspace_id=gate.workspace_id)
    # Only an active connection takes an answer: an expired one can never send (reconnecting always
    # makes a new connection row and closes this one's proposals), and a standing permission given
    # on it would be lost with it.
    if (
        current is None
        or current.connection_id != proposal.connection_id
        or current.status != "active"
    ):
        raise CrmAnswerRefused(
            409,
            "CRM_CONNECTION_CHANGED",
            "the CRM connection this card was made for is no longer active (expired, reconnected "
            "or switched); reconnect the CRM and ask Clue to propose the changes again",
        )
    if decision != "approved":
        if choices.selected_write_ids or choices.always_allow:
            raise CrmAnswerRefused(
                422, "CRM_WRITE_CHOICE_UNEXPECTED", "declining the card carries no choices"
            )
        return
    if not choices.selected_write_ids:
        raise CrmAnswerRefused(
            422, "CRM_WRITE_NOTHING_SELECTED", "tick at least one change to allow"
        )
    known = {
        UUID(str(write_id))
        for (write_id,) in await conn.execute(
            text("SELECT write_id FROM crm_write WHERE proposal_id = :id"),
            {"id": proposal.proposal_id},
        )
    }
    if not set(choices.selected_write_ids) <= known:
        raise CrmAnswerRefused(
            422, "CRM_WRITE_UNKNOWN_CHANGE", "a ticked change is not part of this card"
        )
    offered = _offered_scopes(gate)
    if not set(choices.always_allow) <= offered:
        raise CrmAnswerRefused(
            422,
            "CRM_WRITE_SCOPE_NOT_OFFERED",
            "the card did not offer that standing permission (overwriting a value a person set "
            "always asks)",
        )


async def answer_summary(
    conn: AsyncConnection,
    gate: AgentGateRow,
    *,
    decision: str,
    selected_write_ids: list[UUID] | None,
    always_allow: list[str] | None,
) -> str:
    """The sentence the agent reads in the answering turn.

    Derived from the immutable card and the changes a standing permission covered when the
    proposal was logged, so a retried click yields the same sentence."""
    choices = _choices(decision, selected_write_ids, always_allow)
    snapshot = gate.subject_snapshot
    shown = _shown_write_ids(snapshot)
    covered = int(
        await conn.scalar(
            text(
                "SELECT count(*) FROM crm_write w JOIN crm_write_proposal p "
                "ON p.proposal_id = w.proposal_id WHERE p.gate_id = :gate "
                "AND w.covered_by LIKE 'grant:%'"
            ),
            {"gate": gate.gate_id},
        )
        or 0
    )
    if decision != "approved":
        sentence = "Did not allow these changes; nothing was sent"
        if covered:
            sentence += f", including the {_changes(covered)} a standing permission covered"
        return sentence + "."
    allowed = len({str(i) for i in choices.selected_write_ids} & shown)
    sentence = f"Allowed {allowed} of {_changes(len(shown))}"
    phrases = _phrases(snapshot)
    granted = [phrases.get(scope, scope) for scope in choices.always_allow]
    if granted:
        sentence += "; always allow " + _join(granted)
    if covered:
        sentence += f"; {_changes(covered)} a standing permission covered also go"
    return sentence + "."


def _changes(count: int) -> str:
    return f"{count} change{'' if count == 1 else 's'}"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _phrases(snapshot: dict[str, Any]) -> dict[str, str]:
    offered = snapshot.get("standing_permissions")
    if not isinstance(offered, list):
        return {}
    return {
        str(item["scope_key"]): str(item.get("phrase") or item["scope_key"])
        for item in offered
        if isinstance(item, dict) and isinstance(item.get("scope_key"), str)
    }


def _shown_write_ids(snapshot: dict[str, Any]) -> set[str]:
    """Every change the card listed: its groups' records and its overwrites."""
    shown: set[str] = set()
    for group in _list(snapshot.get("groups")):
        shown.update(str(item["write_id"]) for item in _list(group.get("records")))
    shown.update(str(item["write_id"]) for item in _list(snapshot.get("overwrites")))
    return shown


def _list(value: object) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


async def apply_answer(
    conn: AsyncConnection,
    gate: AgentGateRow,
    *,
    decision: str,
    selected_write_ids: list[UUID] | None,
    always_allow: list[str] | None,
    answered_by_user_id: str,
) -> None:
    """Record the answer on the proposal, in the answer's own transaction (after
    :func:`check_answer` passed)."""
    choices = _choices(decision, selected_write_ids, always_allow)
    proposal = await _proposal_for_gate(conn, gate, lock=True)
    assert proposal is not None  # proved by check_answer in this transaction
    if decision != "approved":
        # The whole proposal is declined, the changes a standing permission covered included.
        await set_proposal_status(
            conn,
            proposal_id=proposal.proposal_id,
            status="declined",
            answered_by_user_id=answered_by_user_id,
        )
        return
    # The card's changes are sent only when ticked; a change a standing permission covered was
    # never on the card and stays chosen.
    await conn.execute(
        text(
            "UPDATE crm_write SET selected = (write_id = ANY(:chosen)), "
            "covered_by = CASE WHEN write_id = ANY(:chosen) THEN :cover END "
            "WHERE proposal_id = :id AND covered_by IS NULL"
        ),
        {
            "id": proposal.proposal_id,
            "chosen": list(choices.selected_write_ids),
            "cover": f"gate:{gate.gate_id}",
        },
    )
    for scope_key in choices.always_allow:
        await insert_grant(
            conn,
            workspace_id=proposal.workspace_id,
            connection_id=proposal.connection_id,
            scope_key=scope_key,
            granted_by_user_id=answered_by_user_id,
        )
    await set_proposal_status(
        conn,
        proposal_id=proposal.proposal_id,
        status="queued",
        answered_by_user_id=answered_by_user_id,
    )
    # The same offer propose_crm_changes makes (one task per connection; a finished one is
    # offered again), in this transaction so the executor never sees the offer before the answer.
    await enqueue_task(
        conn,
        kind=FleetTaskKind.CRM_WRITE,
        project_run_id=ProjectRunId(proposal.connection_id),
        dedup_key=crm_write_dedup_key(proposal.connection_id),
        reopen_terminal=True,
    )


# --- the progress read -----------------------------------------------------------------------


async def proposal_progress(
    conn: AsyncConnection, *, workspace_id: str, proposal_id: UUID
) -> dict[str, Any] | None:
    """What the card shows for its proposal (card spec §3 B–F, §6 ``outcome``); ``None`` when the
    proposal is not this workspace's.

    Only the card's own changes count: those a standing permission covered never appear on a
    card (they show in the agent's next message and in the write log), and unticked ones are not
    listed."""
    proposal = (
        await conn.execute(
            text(
                "SELECT p.status, p.gate_id, p.connection_id, p.answered_by_user_id, "
                "p.answered_at, u.display_name AS answered_by_name, g.subject_snapshot "
                "FROM crm_write_proposal p "
                "LEFT JOIN platform_user u ON u.user_id = p.answered_by_user_id "
                "LEFT JOIN agent_gate g ON g.gate_id = p.gate_id "
                "WHERE p.proposal_id = :id AND p.workspace_id = :ws"
            ),
            {"id": proposal_id, "ws": workspace_id},
        )
    ).first()
    if proposal is None:
        return None
    connection = await get_connection(conn, connection_id=proposal.connection_id)
    snapshot = _snapshot(proposal.subject_snapshot)
    rows = (
        await conn.execute(
            text(
                "SELECT write_id, record_label, field, status, crm_message FROM crm_write "
                "WHERE proposal_id = :id AND selected "
                "AND (covered_by IS NULL OR covered_by NOT LIKE 'grant:%') ORDER BY ordinal"
            ),
            {"id": proposal_id},
        )
    ).all()
    status = {str(row.write_id): row.status for row in rows}
    field_labels = _field_labels(snapshot)

    def tally(write_ids: list[str]) -> dict[str, int]:
        chosen = [status[i] for i in write_ids if i in status]
        return {
            "chosen": len(chosen),
            "done": chosen.count("succeeded"),
            "failed": chosen.count("failed"),
            "skipped": chosen.count("skipped"),
            "pending": sum(s not in ("succeeded", "failed", "skipped") for s in chosen),
        }

    groups = []
    for group in _list(snapshot.get("groups")):
        ids = [str(item["write_id"]) for item in _list(group.get("records"))]
        groups.append(
            {
                "title": group.get("title"),
                "kind": group.get("kind"),
                "object": group.get("object"),
                "fieldLabel": group.get("field_label"),
                "count": group.get("count"),
                **tally(ids),
            }
        )
    overwrites = [
        {
            "writeId": str(item["write_id"]),
            "label": item.get("name"),
            "field": item.get("field_label") or item.get("field"),
            "status": status[str(item["write_id"])],
        }
        for item in _list(snapshot.get("overwrites"))
        if str(item["write_id"]) in status
    ]
    totals = tally(list(status))
    del totals["chosen"]
    answered_at = proposal.answered_at
    state = _CARD_STATE.get(proposal.status, "asking")
    if proposal.status == "finished" and proposal.answered_by_user_id is None:
        # A card nobody answered before a reconnect closed it: nothing was sent.
        state = "closed"
    return {
        "proposalId": str(proposal_id),
        "state": state,
        "provider": None if connection is None else connection.provider,
        "counts": totals,
        "groups": groups,
        "overwrites": overwrites,
        "failed": [
            {
                "writeId": str(row.write_id),
                "label": row.record_label,
                "field": field_labels.get(str(row.write_id), row.field),
                "crmMessage": row.crm_message,
            }
            for row in rows
            if row.status == "failed"
        ],
        "skipped": [
            {"writeId": str(row.write_id), "label": row.record_label, "reason": row.crm_message}
            for row in rows
            if row.status == "skipped"
        ],
        "answeredBy": proposal.answered_by_user_id,
        "answeredByName": proposal.answered_by_name,
        "answeredAt": None if answered_at is None else answered_at.isoformat(),
    }


def _snapshot(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _field_labels(snapshot: dict[str, Any]) -> dict[str, str]:
    """The CRM's own field label of each change the card listed, by write id."""
    labels: dict[str, str] = {}
    for group in _list(snapshot.get("groups")):
        label = group.get("field_label")
        if isinstance(label, str):
            for item in _list(group.get("records")):
                labels[str(item["write_id"])] = label
    for item in _list(snapshot.get("overwrites")):
        if isinstance(item.get("field_label"), str):
            labels[str(item["write_id"])] = item["field_label"]
    return labels
