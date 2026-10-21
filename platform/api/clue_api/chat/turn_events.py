"""The turn-scoped durable event outbox — the write and read halves of the turn stream.

FI Lane D slice **D3**, charter §3-P4 / §3.2 / §3.6. The B4 treaty stream taught the shape this
copies: one durable append per event, a ``bigserial`` cursor a consumer tracks with
``Last-Event-ID``, at-least-once delivery deduplicated by that cursor, and a replay horizon that
turns an un-replayable cursor into ``stream.reset`` instead of a silent gap. What it could **not**
reuse is the table: ``run_event.run_id`` is ``NOT NULL`` and a conversation turn has no project run
(it may *launch* one, later, if the human approves). Hence ``agent_turn_event_stream``.

**Why this lives in ``clue_api`` and not in ``clue_projections``.** Emitting is a write, and the
projections package is MVCC-only by contract. The B4 outbox lives in ``clue_research.durable``
because it is *run* machinery; a turn event is *agent-plane* machinery, whose durable writers
(``DbAgentTurnJournal``, ``DurableAgentArtifactStore``) already live here at the composition root.

**What this table is not.** It is a transport buffer, not the record of the turn. Everything a
consumer could lose to pruning is re-derivable from the durable authority — the turn journal, the
finalization commit, ``agent_thread_message`` — which is exactly why §3.6 makes cold load a
paginated *message* read and never an SSE replay, and why :func:`prune_turn_events` may delete.

Two identifiers, two jobs (§3.2):

* ``event_id`` — globally monotone. It is the SSE ``id:`` field, the ``Last-Event-ID`` cursor, and
  the deduplication key for at-least-once delivery.
* ``sequence`` — monotone *within one turn*, assigned in SQL from the turn's own high-water mark
  under a ``UNIQUE (turn_id, sequence)`` constraint. A consumer can therefore gap-check one turn
  without observing the rest of the workspace.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import UtcDatetime, decode_jsonb, serialize_value_json

__all__ = [
    "LIFECYCLE_EVENT_TYPES",
    "TERMINAL_TURN_EVENTS",
    "TURN_EVENT_TYPES",
    "TurnEventRow",
    "TurnEventType",
    "TurnReplayPlan",
    "emit_turn_event",
    "list_turn_events",
    "next_generation_attempt",
    "plan_turn_replay",
    "prune_turn_events",
    "turn_event_created_at",
    "turn_stream_has_event",
    "turn_text_deltas",
]


class TurnEventType(StrEnum):
    """The closed §3.2 vocabulary, mirrored by a SQL CHECK (migration ``98a5ddafa21b``).

    ``stream.hello`` is deliberately absent: it is generated at connect and never stored (the B4
    surface does the same). ``stream.reset`` *is* here, for the single durable case §3.3(5) names —
    a reconciliation mismatch between the streamed deltas and the durable assistant message, which
    must instruct every consumer, present and future, to re-fetch the canonical message rather than
    trust the projection.
    """

    TURN_ACCEPTED = "turn.accepted"
    TURN_STARTED = "turn.started"
    TURN_AWAITING_INPUT = "turn.awaiting_input"
    TURN_COMPLETED = "turn.completed"
    TURN_FAILED = "turn.failed"
    TURN_CANCELLED = "turn.cancelled"
    TURN_RETRYING = "turn.retrying"
    PART_CREATED = "part.created"
    PART_UPDATED = "part.updated"
    PART_COMPLETED = "part.completed"
    PART_FAILED = "part.failed"
    PART_RESET = "part.reset"
    TEXT_START = "text.start"
    TEXT_DELTA = "text.delta"
    TEXT_END = "text.end"
    STREAM_RESET = "stream.reset"
    # P3.7 delta 8 (PD-part3 §3-8): the design-leg lifecycle, on the same thread stream the
    # speaker chip and the transcript already follow. Emitted transactionally with the durable
    # leg transition they announce (the open/finish tools; the leg runner), each carrying
    # ``leg_id`` in the payload — ``leg.closed`` also carries the exit ``reason``. The spec's
    # sketch said "closing"; with turn-terminal legs the close is one atomic journal+flip, so a
    # separate closing frame would announce a phase that cannot be observed — dropped in favor
    # of ``leg.reopened`` (the §2.2 mis-exit re-delegation), which IS a real, durable transition.
    LEG_OPENED = "leg.opened"
    LEG_AWAITING_USER = "leg.awaiting_user"
    LEG_CLOSED = "leg.closed"
    LEG_REOPENED = "leg.reopened"
    # Scene live-streaming rung A: the design agent commits its work in progress mid-run (P0.4),
    # and each commit marks the design run's own event stream. This is that mark, forwarded onto
    # the leg's thread by the inline design lane (``clue_api.design_fleet``) so a marketer sees
    # the document advance instead of a spinner. Progress, not lifecycle: a checkpoint frame
    # announces a version the document ALREADY holds, it never ends or gates a turn, and losing
    # one costs a redraw — which is why the forwarder is best-effort by construction.
    DESIGN_CHECKPOINT = "design.checkpoint"
    # Scene live-streaming rung B: the operations of a single mid-run mutation, streamed as the
    # agent makes it, with ``operations_total`` — the position that batch ends at in the run's
    # operation ledger, the same ledger a checkpoint frame counts. Unlike a checkpoint, an op
    # batch announces work that is NOT yet durable: a consumer may render it optimistically and
    # reconcile against the next checkpoint by subtracting the positions. Progress, not
    # lifecycle, and best-effort for the same reason — a lost batch costs a frame of animation,
    # never correctness, because the checkpoint behind it still names the durable version.
    DESIGN_OP_BATCH = "design.op_batch"


#: The stored vocabulary as plain strings, kept equal to the enum (and to the DB CHECK) by a test —
#: the same guard ``RUN_EVENT_TOPICS`` gives the treaty stream.
TURN_EVENT_TYPES: tuple[str, ...] = tuple(member.value for member in TurnEventType)

#: The event types that end a turn. "Is this turn still live?" is derived from their presence,
#: never from a mutable status column.
TERMINAL_TURN_EVENTS: Final = frozenset(
    {
        TurnEventType.TURN_COMPLETED,
        TurnEventType.TURN_FAILED,
        TurnEventType.TURN_CANCELLED,
        TurnEventType.TURN_AWAITING_INPUT,
    }
)

#: A turn's lifecycle frames — the only frames a thread stream sends (CRM trial 1, F2). They say
#: that a turn exists and where it is; its parts, text and tools stay on the turn's own stream.
LIFECYCLE_EVENT_TYPES: Final = frozenset(
    {
        TurnEventType.TURN_ACCEPTED.value,
        TurnEventType.TURN_STARTED.value,
        TurnEventType.TURN_AWAITING_INPUT.value,
        TurnEventType.TURN_COMPLETED.value,
        TurnEventType.TURN_FAILED.value,
        TurnEventType.TURN_CANCELLED.value,
        TurnEventType.TURN_RETRYING.value,
    }
)

#: The wire schema version every envelope carries (§3.2's ``schema_version``). A consumer that does
#: not know this version fails at its repository boundary rather than rendering guessed UI (§3.2).
TURN_STREAM_SCHEMA_VERSION: Final = "1"


class TurnEventRow(BaseModel):
    """One persisted frame — the durable form of the §3.2 envelope."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: int
    workspace_id: str
    project_id: str
    thread_id: str
    turn_id: UUID
    sequence: int
    generation_attempt_id: UUID | None = None
    event_type: str
    part_id: str | None = None
    part_kind: str | None = None
    message_id: UUID | None = None
    run_id: UUID | None = None
    delta_index: int | None = None
    payload: dict[str, JsonValue]
    occurred_at: UtcDatetime

    def envelope(self) -> dict[str, JsonValue]:
        """The §3.2 envelope this frame is sent as — ``data:`` of one SSE frame.

        Optional members are omitted rather than sent as ``null`` so a consumer's schema can
        distinguish "this event has no part" from "this event has a part that is null".
        """

        body: dict[str, JsonValue] = {
            "schema_version": TURN_STREAM_SCHEMA_VERSION,
            "event_id": self.event_id,
            "sequence": self.sequence,
            "occurred_at": self.occurred_at.isoformat(),
            "project_id": self.project_id,
            "thread_id": self.thread_id,
            "turn_id": str(self.turn_id),
            "type": self.event_type,
        }
        if self.generation_attempt_id is not None:
            body["generation_attempt_id"] = str(self.generation_attempt_id)
        if self.message_id is not None:
            body["message_id"] = str(self.message_id)
        if self.part_id is not None:
            body["part_id"] = self.part_id
        if self.part_kind is not None:
            body["part_kind"] = self.part_kind
        if self.run_id is not None:
            body["run_id"] = str(self.run_id)
        if self.delta_index is not None:
            body["delta_index"] = self.delta_index
        body.update(self.payload)
        return body


_COLUMNS = (
    "event_id, workspace_id, project_id, thread_id, turn_id, sequence, generation_attempt_id, "
    "event_type, part_id, part_kind, message_id, run_id, delta_index, payload, occurred_at"
)

# The per-turn ordinal is assigned in the INSERT itself, from the turn's own high-water mark.
# One generation legitimately has multiple emitters: the streaming callback, tool-part projection,
# and terminal/finalization path can append from independent transactions. Serialize only the
# high-water-mark allocation for this turn with a transaction-scoped advisory lock. Locking is a
# separate statement on purpose: PostgreSQL fixes one statement's MVCC snapshot before a lock wait,
# so a lock CTE and the max-read in the same statement can still observe the pre-wait value.
# Without the lock, two writers can both observe N and one loses `UNIQUE (turn_id, sequence)`,
# silently degrading the stream even though the durable turn still completes.
_TURN_SEQUENCE_LOCK_SQL = text("SELECT pg_advisory_xact_lock(hashtextextended(:turn_lock_key, 0))")

_EMIT_SQL = text(
    f"""
    INSERT INTO agent_turn_event_stream
        (workspace_id, project_id, thread_id, turn_id, sequence, generation_attempt_id,
         event_type, part_id, part_kind, message_id, run_id, delta_index, payload)
    SELECT
        :workspace_id, :project_id, :thread_id, :turn_id,
        COALESCE(
            (SELECT max(sequence) FROM agent_turn_event_stream WHERE turn_id = :turn_id), 0
        ) + 1,
        :generation_attempt_id, :event_type, :part_id, :part_kind, :message_id, :run_id,
        :delta_index, CAST(:payload AS jsonb)
    RETURNING {_COLUMNS}
    """
)


async def emit_turn_event(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    thread_id: str,
    turn_id: UUID,
    event_type: TurnEventType,
    generation_attempt_id: UUID | None = None,
    part_id: str | None = None,
    part_kind: str | None = None,
    message_id: UUID | None = None,
    run_id: UUID | None = None,
    delta_index: int | None = None,
    payload: dict[str, JsonValue] | None = None,
) -> TurnEventRow:
    """Append one frame and return it (with its assigned ``event_id`` and ``sequence``).

    Transactional in the caller's connection. Emission is at-least-once and cursor-idempotent: a
    consumer deduplicates on ``event_id``, so a re-delivered frame is harmless, and a crash between
    the durable turn write and this append simply drops a frame the durable state can still explain.
    """

    await conn.execute(_TURN_SEQUENCE_LOCK_SQL, {"turn_lock_key": str(turn_id)})
    row = (
        (
            await conn.execute(
                _EMIT_SQL,
                {
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "thread_id": thread_id,
                    "turn_id": turn_id,
                    "generation_attempt_id": generation_attempt_id,
                    "event_type": event_type.value,
                    "part_id": part_id,
                    "part_kind": part_kind,
                    "message_id": message_id,
                    "run_id": run_id,
                    "delta_index": delta_index,
                    "payload": serialize_value_json(payload if payload is not None else {}),
                },
            )
        )
        .mappings()
        .one()
    )
    return _row(dict(row))


async def list_turn_events(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    turn_id: UUID | None = None,
    thread_id: str | None = None,
    after_event_id: int = 0,
    limit: int = 1000,
    event_types: Collection[str] | None = None,
) -> tuple[TurnEventRow, ...]:
    """Read a tenant's turn frames in cursor order — the replay surface.

    Scoped in SQL on ``workspace_id`` on every statement: a cross-workspace read returns nothing,
    never another tenant's conversation. ``turn_id`` narrows to one turn's stream; ``thread_id``
    narrows to a whole conversation; ``event_types`` keeps only those frames (filtered in SQL, so
    ``limit`` counts only the frames returned). Read-only.
    """

    clauses = ""
    params: dict[str, object] = {
        "workspace_id": workspace_id,
        "after_event_id": after_event_id,
        "row_limit": limit,
    }
    if turn_id is not None:
        clauses += "AND turn_id = :turn_id "
        params["turn_id"] = turn_id
    if thread_id is not None:
        clauses += "AND thread_id = :thread_id "
        params["thread_id"] = thread_id
    if event_types is not None:
        clauses += "AND event_type = ANY(:event_types) "
        params["event_types"] = sorted(event_types)
    rows = (
        (
            await conn.execute(
                text(
                    f"SELECT {_COLUMNS} FROM agent_turn_event_stream "
                    "WHERE workspace_id = :workspace_id AND event_id > :after_event_id "
                    f"{clauses}"
                    "ORDER BY event_id LIMIT :row_limit"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    return tuple(_row(dict(row)) for row in rows)


async def turn_event_created_at(
    conn: AsyncConnection, *, workspace_id: str, event_id: int
) -> UtcDatetime | None:
    """When the tenant's frame at ``event_id`` was emitted — the replay-horizon check.

    ``None`` for a cursor this tenant never had (unknown, pruned, corrupted, cross-environment, or
    another tenant's), which the replay planner treats conservatively as a reset.
    """

    row = (
        await conn.execute(
            text(
                "SELECT occurred_at FROM agent_turn_event_stream "
                "WHERE workspace_id = :workspace_id AND event_id = :event_id"
            ),
            {"workspace_id": workspace_id, "event_id": event_id},
        )
    ).one_or_none()
    return row[0] if row is not None else None


@dataclass(frozen=True, slots=True)
class TurnReplayPlan:
    """The reconnect decision for one attaching consumer.

    ``effective_cursor`` is the load-bearing field, and it is ``0`` on reset — never the consumer's
    unusable cursor, which as a tail floor would match nothing forever (a permanently dead "live"
    stream). The same defect B4's ``plan_replay`` documents; the same fix.
    """

    reset: bool
    backlog: tuple[TurnEventRow, ...]
    effective_cursor: int


async def plan_turn_replay(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    turn_id: UUID | None,
    thread_id: str | None = None,
    last_event_id: int | None,
    horizon_s: float,
    now: datetime | None = None,
    limit: int = 1000,
    event_types: Collection[str] | None = None,
) -> TurnReplayPlan:
    """Plan a consumer's replay from its ``Last-Event-ID`` cursor (§3.6).

    * No cursor (a fresh attach) → no reset; the backlog is everything so far.
    * A cursor inside the horizon → no reset; the backlog is ``event_id > cursor``, in order, and
      byte-identical to what the first connect delivered.
    * A cursor outside the horizon, or one this tenant never had (pruned, corrupted, foreign) →
      **reset**: the surface emits ``stream.reset``, the consumer re-fetches the canonical message
      and part projections, and both the backlog and the live tail restart from zero.
    """

    cursor = last_event_id if last_event_id is not None and last_event_id > 0 else 0
    reset = False
    if cursor > 0:
        moment = now if now is not None else datetime.now(UTC)
        cutoff = moment - timedelta(seconds=horizon_s)
        seen_at = await turn_event_created_at(conn, workspace_id=workspace_id, event_id=cursor)
        reset = seen_at is None or seen_at < cutoff
    effective_cursor = 0 if reset else cursor
    backlog = await list_turn_events(
        conn,
        workspace_id=workspace_id,
        turn_id=turn_id,
        thread_id=thread_id,
        after_event_id=effective_cursor,
        limit=limit,
        event_types=event_types,
    )
    return TurnReplayPlan(reset=reset, backlog=backlog, effective_cursor=effective_cursor)


async def turn_text_deltas(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    turn_id: UUID,
    part_id: str,
    generation_attempt_id: UUID,
) -> tuple[str, ...]:
    """Every persisted text delta of one part of one attempt, in ``delta_index`` order.

    This is what reconciliation (§3.3(5)) joins: the proof is what the *outbox* holds — what a
    consumer would actually have received — not what an in-memory buffer believes it emitted.
    """

    rows = (
        await conn.execute(
            text(
                "SELECT payload ->> 'delta' FROM agent_turn_event_stream "
                "WHERE workspace_id = :workspace_id AND turn_id = :turn_id "
                "AND part_id = :part_id AND generation_attempt_id = :attempt_id "
                "AND event_type = 'text.delta' "
                "ORDER BY delta_index"
            ),
            {
                "workspace_id": workspace_id,
                "turn_id": turn_id,
                "part_id": part_id,
                "attempt_id": generation_attempt_id,
            },
        )
    ).scalars()
    return tuple("" if value is None else str(value) for value in rows)


async def turn_stream_has_event(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    turn_id: UUID,
    event_type: TurnEventType,
) -> bool:
    """Whether this turn already carries a frame of ``event_type``.

    The idempotence check behind a lifecycle frame that two different processes can legitimately
    try to emit: ``turn.accepted`` is written by the HTTP route the moment a turn is durable, and
    the worker emits it only if it finds none — which is what keeps a turn accepted off-route (the
    dev trial, a test harness) announceable without ever announcing a turn twice.
    """

    row = (
        await conn.execute(
            text(
                "SELECT 1 FROM agent_turn_event_stream "
                "WHERE workspace_id = :workspace_id AND turn_id = :turn_id "
                "AND event_type = :event_type LIMIT 1"
            ),
            {
                "workspace_id": workspace_id,
                "turn_id": turn_id,
                "event_type": event_type.value,
            },
        )
    ).first()
    return row is not None


async def next_generation_attempt(
    conn: AsyncConnection, *, workspace_id: str, turn_id: UUID
) -> tuple[int, tuple[UUID, ...]]:
    """The ordinal of the attempt about to start, and every attempt already recorded for this turn.

    Derived from the outbox rather than stored, because the outbox *is* the record of what was
    streamed: a turn whose first attempt died mid-generation has that attempt's frames, and the
    next attempt must be a different identity so no consumer can splice the two continuations
    together (§3.3(6)).
    """

    rows = (
        await conn.execute(
            text(
                "SELECT DISTINCT generation_attempt_id, min(event_id) AS first_event "
                "FROM agent_turn_event_stream "
                "WHERE workspace_id = :workspace_id AND turn_id = :turn_id "
                "AND generation_attempt_id IS NOT NULL "
                "GROUP BY generation_attempt_id ORDER BY first_event"
            ),
            {"workspace_id": workspace_id, "turn_id": turn_id},
        )
    ).mappings()
    prior = tuple(UUID(str(row["generation_attempt_id"])) for row in rows)
    return len(prior) + 1, prior


_PRUNE_SQL = text(
    """
    DELETE FROM agent_turn_event_stream
    WHERE turn_id IN (
        SELECT turn_id
        FROM agent_turn_event_stream
        WHERE NOT EXISTS (
            SELECT 1 FROM agent_turn_control_request c
            WHERE c.turn_id=agent_turn_event_stream.turn_id AND c.kind='stop'
              AND NOT EXISTS (SELECT 1 FROM agent_turn_stop_ack a WHERE a.control_id=c.control_id)
        )
        GROUP BY turn_id
        HAVING bool_or(event_type IN ('turn.completed', 'turn.failed', 'turn.cancelled',
                                      'turn.awaiting_input'))
           AND max(occurred_at) < :cutoff
        LIMIT :turn_limit
    )
    """
)


async def prune_turn_events(
    conn: AsyncConnection,
    *,
    retention_s: float,
    now: datetime | None = None,
    turn_limit: int = 500,
) -> int:
    """Delete the frames of **terminal** turns older than the retention window. Returns the count.

    The explicit retention policy §3.3(7) demands, and the reason ``DELETE`` is not blocked on this
    one agent-plane table. Three properties make it safe:

    * **Only terminal turns.** A turn with no terminal event is still live (or crashed and about to
      be retried) and keeps every frame, however old — pruning a live attempt would strand an
      attached consumer mid-generation.
    * **Whole turns.** A turn is pruned entirely or not at all, so a surviving stream is never a
      partial view with a hole in the middle.
    * **Nothing durable is lost.** The transcript, the finalization commit and the turn journal are
      untouched; a consumer whose cursor was pruned gets ``stream.reset`` and re-fetches them.

    Operationally the window should be ``>= CLUE_SSE_REPLAY_HORIZON_S``: pruning inside the horizon
    would promise a replay the table can no longer serve (the reset path is still correct, just
    needlessly frequent).
    """

    moment = now if now is not None else datetime.now(UTC)
    cutoff = moment - timedelta(seconds=retention_s)
    result = await conn.execute(_PRUNE_SQL, {"cutoff": cutoff, "turn_limit": turn_limit})
    return int(result.rowcount or 0)


def _row(row: dict[str, object]) -> TurnEventRow:
    return TurnEventRow.model_validate({**row, "payload": decode_jsonb(row["payload"])})
