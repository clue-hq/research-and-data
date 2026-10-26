"""Read projections over the D4 gate substrate — the durable narration facts, not a stream.

FI Lane D slice **D4**, deliverable 6. D3 owns every byte that reaches a client over SSE; what D4
owes it is the *durable linkage* those parts render: which gate was presented in which turn, what it
asked for, whether it was answered, by which turn, and — for an approved directive-confirmation —
which research run that turn's authority ended up launching.

Everything here is a join over rows that already exist. Nothing is stored a second time, nothing is
derived that a receipt does not already state, and "open" is the absence of an answer row (ratified
§6-D3), never a column — with one more absence for one kind: a CRM write permission card is also
closed once its proposal has moved on without an answer (a newer card ``replaced`` it, or a
reconnect closed it), because such a card can never be answered (:data:`GATE_WITHDRAWN_SQL`):

* :func:`open_gate_kinds_for_threads` answers the sidebar's question ("does this conversation want
  something from me?") for many threads at once, which is what the thread list needs;
* :func:`thread_gates` is the transcript's question — every gate of one thread, in order, with its
  answer and its downstream launch — and is the shape a ``gate`` part and the ``task`` part that
  follows an approval both read.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text

from clue_db import ConnFactory, transaction

__all__ = [
    "GATE_WITHDRAWN_SQL",
    "GateAnswerView",
    "GateLaunchView",
    "GateView",
    "open_gate_kinds_for_threads",
    "thread_gates",
]


#: A SQL predicate over an ``agent_gate`` row aliased ``g``: the gate can no longer be answered
#: although nobody answered it. Today only a CRM write permission card is withdrawn, when its
#: proposal is no longer waiting for it (``crm_write_proposal.status`` is ``replaced`` by a newer
#: card, or ``finished`` because a reconnect closed it). Derived from the proposal row the card
#: belongs to, never stored on the gate (gates and answers are append-only), and shared by every
#: place that derives openness so none of them drifts.
GATE_WITHDRAWN_SQL = (
    "EXISTS (SELECT 1 FROM crm_write_proposal withdrawn_p "
    "WHERE withdrawn_p.gate_id = g.gate_id AND withdrawn_p.workspace_id = g.workspace_id "
    "AND withdrawn_p.status NOT IN ('prepared', 'awaiting_permission'))"
)


class GateAnswerView(BaseModel):
    """How a gate was answered, if it was."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn_id: str
    action_ref: str
    decision: str
    expected_subject_sha256: str
    decision_payload: dict[str, JsonValue]
    selected_option_ref: str | None
    answered_by_user_id: str
    answered_at: datetime


class GateLaunchView(BaseModel):
    """The research run an approved gate's confirming turn actually authorized.

    Joined on the ``turn-action:`` receipt rather than on a foreign key, because that receipt *is*
    the link: the launcher persists it as ``entity_research_run.source_action_ref`` and repeats it
    inside ``approval_refs``. A gate whose approval has not (yet) been spent simply has none of
    these, which is the honest answer while the agent is still deciding.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    research_run_id: str
    run_kind: str
    run_state: str
    source_action_ref: str
    approval_refs: tuple[str, ...]


class GateView(BaseModel):
    """One gate, its answer, and anything the answer launched."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    gate_id: str
    workspace_id: str
    project_id: str
    thread_id: str
    turn_id: str
    kind: str
    subject_ref: str
    subject_revision: int | None
    expected_subject_sha256: str
    subject_snapshot: dict[str, JsonValue]
    permitted_decisions: tuple[str, ...]
    max_spend_cents: Decimal | None
    currency: str | None
    addressee_user_id: str
    created_at: datetime
    snapshot_erased_at: datetime | None = None
    snapshot_erasure_reason: str | None = None
    answer: GateAnswerView | None
    launches: tuple[GateLaunchView, ...]
    #: Unanswered and no longer answerable (:data:`GATE_WITHDRAWN_SQL`).
    withdrawn: bool = False

    @property
    def is_open(self) -> bool:
        return self.answer is None and self.snapshot_erased_at is None and not self.withdrawn


_OPEN_KINDS_SQL = text(
    f"""
    SELECT g.thread_id, g.kind
    FROM agent_gate g
    LEFT JOIN agent_gate_answer a
      ON a.gate_id = g.gate_id AND a.workspace_id = g.workspace_id
    WHERE g.workspace_id = :workspace_id
      AND g.thread_id = ANY(CAST(:thread_ids AS text[]))
      AND a.gate_id IS NULL AND g.snapshot_erased_at IS NULL
      AND NOT {GATE_WITHDRAWN_SQL}
    ORDER BY g.created_at, g.gate_id
    """
)


async def open_gate_kinds_for_threads(
    *,
    workspace_id: str,
    thread_ids: tuple[str, ...],
    conn_factory: ConnFactory = transaction,
) -> dict[str, tuple[str, ...]]:
    """The unanswered gate kinds of each thread, oldest first. Threads with none are absent.

    One query for a page of threads rather than one per thread: the sidebar renders a whole list,
    and a per-row read would make "is anyone waiting on me?" cost a query per conversation.
    """

    if not thread_ids:
        return {}
    async with conn_factory() as conn:
        rows = (
            await conn.execute(
                _OPEN_KINDS_SQL,
                {"workspace_id": workspace_id, "thread_ids": list(thread_ids)},
            )
        ).all()
    by_thread: dict[str, list[str]] = {}
    for thread_id, kind in rows:
        by_thread.setdefault(str(thread_id), []).append(str(kind))
    return {thread: tuple(kinds) for thread, kinds in by_thread.items()}


_THREAD_GATES_SQL = text(
    f"""
    SELECT {GATE_WITHDRAWN_SQL} AS withdrawn,
           g.gate_id, g.workspace_id, g.project_id, g.thread_id, g.turn_id, g.kind,
           g.subject_ref, g.subject_revision, g.expected_subject_sha256, g.subject_snapshot,
           g.permitted_decisions, g.max_spend_cents, g.currency, g.addressee_user_id, g.created_at,
           g.snapshot_erased_at, g.snapshot_erasure_reason,
           a.turn_id AS answer_turn_id, a.action_ref, a.decision,
           a.expected_subject_sha256 AS answer_subject_sha256, a.decision_payload,
           a.selected_option_ref, a.answered_by_user_id, a.answered_at
    FROM agent_gate g
    LEFT JOIN agent_gate_answer a
      ON a.gate_id = g.gate_id AND a.workspace_id = g.workspace_id
    WHERE g.workspace_id = :workspace_id AND g.thread_id = :thread_id
    ORDER BY g.created_at, g.gate_id
    """
)

#: The launch a confirming turn's receipt authorized. ``source_action_ref`` lives on the fleet
#: control row the launcher writes in the same transaction as the run; ``approval_refs`` lives
#: inside the run's frozen ``lifecycle_json`` selection (that is where the launcher persists the
#: ``(source_action_ref, confirming_turn_ref)`` pair). Both are read as-is — this projection states
#: what the launcher recorded and never recomputes it.
_LAUNCHES_SQL = text(
    """
    SELECT r.research_run_id,
           r.run_kind,
           r.state,
           f.source_action_ref,
           r.lifecycle_json -> 'selection' ->> 'approval_refs' AS approval_refs
    FROM entity_research_account_fleet f
    JOIN entity_research_run r
      ON r.research_run_id = f.research_run_id AND r.workspace_id = f.workspace_id
    WHERE f.workspace_id = :workspace_id
      AND f.source_action_ref = ANY(CAST(:action_refs AS text[]))
    ORDER BY r.created_at, r.research_run_id
    """
)


async def thread_gates(
    *,
    workspace_id: str,
    thread_id: str,
    conn_factory: ConnFactory = transaction,
) -> tuple[GateView, ...]:
    """Every gate of one thread, oldest first, with its answer and its launches."""

    async with conn_factory() as conn:
        rows = (
            (
                await conn.execute(
                    _THREAD_GATES_SQL,
                    {"workspace_id": workspace_id, "thread_id": thread_id},
                )
            )
            .mappings()
            .all()
        )
        action_refs = [str(row["action_ref"]) for row in rows if row["action_ref"] is not None]
        launch_rows = (
            (
                await conn.execute(
                    _LAUNCHES_SQL,
                    {"workspace_id": workspace_id, "action_refs": action_refs},
                )
            )
            .mappings()
            .all()
            if action_refs
            else []
        )
    launches_by_ref: dict[str, list[GateLaunchView]] = {}
    for row in launch_rows:
        launches_by_ref.setdefault(str(row["source_action_ref"]), []).append(
            GateLaunchView(
                research_run_id=str(row["research_run_id"]),
                run_kind=str(row["run_kind"]),
                run_state=str(row["state"]),
                source_action_ref=str(row["source_action_ref"]),
                approval_refs=_approval_refs(row["approval_refs"]),
            )
        )
    views: list[GateView] = []
    for row in rows:
        answer = (
            None
            if row["answer_turn_id"] is None
            else GateAnswerView(
                turn_id=str(row["answer_turn_id"]),
                action_ref=str(row["action_ref"]),
                decision=str(row["decision"]),
                expected_subject_sha256=str(row["answer_subject_sha256"]),
                decision_payload=_snapshot(row["decision_payload"]),
                selected_option_ref=(
                    None if row["selected_option_ref"] is None else str(row["selected_option_ref"])
                ),
                answered_by_user_id=str(row["answered_by_user_id"]),
                answered_at=row["answered_at"],
            )
        )
        views.append(
            GateView(
                gate_id=str(row["gate_id"]),
                workspace_id=str(row["workspace_id"]),
                project_id=str(row["project_id"]),
                thread_id=str(row["thread_id"]),
                turn_id=str(row["turn_id"]),
                kind=str(row["kind"]),
                subject_ref=str(row["subject_ref"]),
                subject_revision=row["subject_revision"],
                expected_subject_sha256=str(row["expected_subject_sha256"]),
                subject_snapshot=_snapshot(row["subject_snapshot"]),
                permitted_decisions=tuple(str(item) for item in row["permitted_decisions"]),
                max_spend_cents=row["max_spend_cents"],
                currency=None if row["currency"] is None else str(row["currency"]),
                addressee_user_id=str(row["addressee_user_id"]),
                created_at=row["created_at"],
                snapshot_erased_at=row["snapshot_erased_at"],
                snapshot_erasure_reason=row["snapshot_erasure_reason"],
                answer=answer,
                launches=tuple(
                    launches_by_ref.get(answer.action_ref, ()) if answer is not None else ()
                ),
                withdrawn=answer is None and bool(row["withdrawn"]),
            )
        )
    return tuple(views)


def _snapshot(value: Any) -> dict[str, JsonValue]:
    if isinstance(value, bytes | bytearray | str):
        decoded = json.loads(value)
        assert isinstance(decoded, dict)
        return decoded
    assert isinstance(value, dict)
    return value


def _approval_refs(value: Any) -> tuple[str, ...]:
    """``approval_refs`` as the launcher froze it inside the run's selection payload."""

    if value is None:
        return ()
    decoded = json.loads(value) if isinstance(value, bytes | bytearray | str) else value
    if not isinstance(decoded, list):
        return ()
    return tuple(str(item) for item in decoded)
