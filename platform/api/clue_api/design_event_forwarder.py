"""The design-run event tail — the one place a design run's progress becomes chat frames.

Lifted verbatim out of ``clue_api.design_fleet`` (which had reached its size ceiling) when scene
live-streaming rung B added its second filter. The lane driver still owns the *lifecycle* of this
tail — it starts one per drive and drains it once more at the end — but the mapping from a design
run's outbox rows to a thread's turn frames is its own concern and now has its own file.

Two kinds of frame cross this seam, both progress and neither lifecycle:

* ``design.checkpoint`` (rung A) — the mark a P0.4 checkpoint commit leaves when a verified
  authoring round has been written durably. It announces a version the document ALREADY holds.
* ``design.op_batch`` (rung B) — the operations of a single mutation, streamed as the agent makes
  it, with the position that batch ends at in the run's operation ledger. It announces work that
  is NOT yet durable: the canvas can render it optimistically and reconcile against the next
  checkpoint, which is exactly why both frames report positions in the same ledger.

Nothing here is authoritative. See :class:`_DesignEventForwarder` for why every failure is
swallowed, and why a replayed frame is a no-op rather than a correction.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import text

from clue_api.chat.turn_events import TurnEventType, emit_turn_event
from clue_core import DESIGN_RUN_SUBJECT_KIND, RunEventTopic, serialize_value_json
from clue_execution.run_events import list_run_events
from clue_obs import get_logger

log = get_logger("clue_api.design_event_forwarder")

#: The design run's PROGRESS topic on the shared outbox (``lumen_api.run_stream.PROGRESS_TOPIC``).
#: Taken from the shared ``clue_core`` vocabulary rather than restated: the topic is platform
#: substrate, not a design import, so naming it here costs a worker deployed without the design
#: extras nothing — and a restated literal is exactly how the two halves of one topic drift.
_DESIGN_PROGRESS_TOPIC: Final = RunEventTopic.DESIGN_RUN_EVENT.value

#: The design runtime's name for one committed P0.4 checkpoint
#: (``lumen_api.main.SCENE_CHECKPOINT_EVENT``). Restated as a literal, unlike the topic above:
#: it is a DESIGN constant, and every design import on this path is lazy by contract — a platform
#: worker deployed without the design extras must still compose.
_SCENE_CHECKPOINT_EVENT: Final = "scene_checkpoint_committed"

#: The design events this lane forwards onto the leg's chat thread, each mapped to the turn-event
#: type it becomes and the payload keys carried across. Everything else the design vocabulary
#: emits (~60 names, open by design) stays on the design run's own stream. A key the design event
#: did not carry is simply absent from the frame — the forwarder never invents one, and never
#: passes one through that the mapping does not name (``reason`` is a checkpoint's internal
#: bookkeeping, not something a consumer should render).
_FORWARDED_DESIGN_EVENTS: Final[dict[str, tuple[TurnEventType, tuple[str, ...]]]] = {
    _SCENE_CHECKPOINT_EVENT: (
        TurnEventType.DESIGN_CHECKPOINT,
        ("document_id", "version", "operations", "preflight_clean"),
    ),
}

#: The payload keys an op-bearing design event contributes to its ``design.op_batch`` frame.
#: The rest of a sink push (``actor``, the two summaries, ``diagnostic_count``) is the design
#: run's own stream's business; ``document_id`` is not on the event at all and comes from the leg.
_OP_BATCH_KEYS: Final = ("operations", "operations_total", "iteration")

#: How much serialized ``operations`` a single frame may carry. Past it the frame forwards
#: POSITION-ONLY (``operations`` dropped, ``operations_total`` kept) — never a truncated batch,
#: because half an operation list applied to a canvas is a corrupted document, whereas a bare
#: position is honest: the client stops rendering optimistically and waits for the checkpoint
#: behind it, which names a version it can simply reload. Measured on exactly the serialization
#: the row would store, so the limit means what an operator reading it thinks it means.
_MAX_OPERATIONS_BYTES: Final = 256 * 1024

#: One tail poll's worth of rows. A chatty turn simply catches up on the next poll.
_FORWARD_PAGE_LIMIT: Final = 500


@dataclass(frozen=True, slots=True)
class _ThreadTurnIdentity:
    """Where a forwarded frame lands: the leg turn, on its thread, in its project — and which
    document its op batches are edits to.

    ``document_id`` is the leg's own pin (``design_leg.document_id``, frozen onto the envelope by
    ``DesignLegTurnRunner._envelope``), which is the same document a checkpoint mark names.
    Checkpoint frames take it from the mark; op batches have no such key of their own, so a
    document-less leg forwards no op batches at all rather than a frame naming nothing.
    """

    workspace_id: str
    project_id: str
    thread_id: str
    turn_id: UUID
    document_id: str | None


class _DesignEventForwarder:
    """Tail one design run's outbox and forward its progress marks onto the leg's thread.

    Two frames come out: a ``design.checkpoint`` for each committed P0.4 checkpoint (rung A), and
    a ``design.op_batch`` for each op-bearing mutation between them (rung B). Both are progress,
    neither is lifecycle, and both are best-effort.

    **Best-effort, always.** A design turn's authority is its run row and the durable document
    version its checkpoints already committed; a frame is only the announcement. So every failure
    here — an unreadable outbox, a refused emit, a turn identity that cannot be resolved — is
    logged and swallowed. It may never fail the drive, delay it, or disturb the turn's own
    lifecycle frames, which a different writer owns.

    **At most once per drive attempt.** The cursor is this object's, and this object belongs to
    one :meth:`InlineDesignLaneDriver.drive` call. A retried turn re-forwards what its previous
    attempt already sent; that is deliberate and cheap — a checkpoint frame carries the document
    version it announces, and the consumer applies versions monotonically, so a replay is a
    no-op rather than a correction. Cross-attempt deduplication would need durable state the
    announcement does not deserve.

    **Fencing.** The outbox carries no lease generation, on the row or in the payload, so a
    reader cannot tell one attempt's rows from another's — and does not have to: the fence lives
    at the *write* site (``lumen_api.run_stream.fenced_emit`` refuses a superseded attempt before
    anything is inserted), so a fenced-out zombie's checkpoint is never a row and can never be
    read here. A *takeover's* checkpoints are forwarded, correctly: the design run may change
    hands, but the platform turn and its thread stay this driver's to project, which is exactly
    why :meth:`InlineDesignLaneDriver.drive` re-joins a takeover's terminal result.
    """

    def __init__(
        self,
        *,
        envelope: Any,
        conn_factory: Any,
        poll_interval_s: float,
    ) -> None:
        self._envelope = envelope
        self._conn_factory = conn_factory
        self._poll_interval_s = poll_interval_s
        self._cursor = 0
        self._identity: _ThreadTurnIdentity | None = None
        self._silent = False
        #: Frames actually appended by this forwarder (see
        #: :attr:`InlineDesignLaneDriver.frames_forwarded`).
        self.forwarded = 0

    async def run(self) -> None:
        """Poll until cancelled. Never raises anything but ``CancelledError``."""

        while True:
            await asyncio.sleep(self._poll_interval_s)
            await self.drain()

    async def drain(self) -> None:
        """One tick: forward every matching row past the cursor. Swallows its own failures."""

        try:
            await self._drain()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning(
                "design_leg.checkpoint_forward_failed",
                run_id=str(getattr(self._envelope, "run_id", None)),
                exc_info=True,
            )

    async def _drain(self) -> None:
        identity = await self._resolve_identity()
        if identity is None:
            return
        async with self._conn_factory() as conn:
            rows = await list_run_events(
                conn,
                workspace_id=identity.workspace_id,
                subject_kind=DESIGN_RUN_SUBJECT_KIND,
                subject_id=str(self._envelope.run_id),
                after_seq=self._cursor,
                limit=_FORWARD_PAGE_LIMIT,
            )
        for row in rows:
            # Advanced BEFORE the emit: a row this attempt has already tried is spent, so a
            # refused emit costs that one frame instead of wedging the tail on it forever.
            self._cursor = row.seq
            frame = _forwarded_frame(row, document_id=identity.document_id)
            if frame is None:
                continue
            event_type, payload = frame
            async with self._conn_factory() as conn:
                await emit_turn_event(
                    conn,
                    workspace_id=identity.workspace_id,
                    project_id=identity.project_id,
                    thread_id=identity.thread_id,
                    turn_id=identity.turn_id,
                    event_type=event_type,
                    payload=payload,
                )
            self.forwarded += 1

    async def _resolve_identity(self) -> _ThreadTurnIdentity | None:
        """The leg turn this run belongs to, resolved once, or ``None`` when there is none.

        Read from the envelope's own frozen ``config['leg']`` block — the identity
        ``DesignLegTurnRunner`` stamped when it dispatched this turn — rather than reconstructed
        from the run row, so the frames land on exactly the turn the leg's own lifecycle frames
        do. The project comes from the thread, which is where the turn stream's foreign key
        points anyway.

        A design run with no leg block (a direct editor turn, or a pre-P3.4 envelope) has no
        thread to announce on: the forwarder goes silent for the rest of the drive rather than
        re-deciding that every tick.
        """

        if self._identity is not None:
            return self._identity
        if self._silent:
            return None
        config = getattr(self._envelope, "config", None)
        leg = config.get("leg") if isinstance(config, dict) else None
        thread_id = leg.get("thread_id") if isinstance(leg, dict) else None
        raw_turn_id = leg.get("agent_turn_id") if isinstance(leg, dict) else None
        turn_id: UUID | None = None
        if isinstance(raw_turn_id, str):
            with contextlib.suppress(ValueError):
                turn_id = UUID(raw_turn_id)
        if not isinstance(thread_id, str) or not thread_id or turn_id is None:
            self._silent = True
            log.info(
                "design_leg.checkpoint_forward_unaddressed",
                run_id=str(self._envelope.run_id),
            )
            return None
        workspace_id = str(self._envelope.workspace_id)
        async with self._conn_factory() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT project_id FROM agent_thread "
                        "WHERE id = :thread AND workspace_id = :workspace"
                    ),
                    {"thread": thread_id, "workspace": workspace_id},
                )
            ).one_or_none()
        if row is None:
            self._silent = True
            log.warning(
                "design_leg.checkpoint_forward_thread_missing",
                run_id=str(self._envelope.run_id),
                thread_id=thread_id,
            )
            return None
        document_id = getattr(self._envelope, "document_id", None)
        self._identity = _ThreadTurnIdentity(
            workspace_id=workspace_id,
            project_id=str(row[0]),
            thread_id=thread_id,
            turn_id=turn_id,
            document_id=str(document_id) if document_id else None,
        )
        return self._identity


def _forwarded_frame(
    row: Any, *, document_id: str | None
) -> tuple[TurnEventType, dict[str, JsonValue]] | None:
    """The turn frame one outbox row becomes, or ``None`` when it is not forwarded.

    The row's payload is the design progress envelope ``{event_type, data}``
    (``lumen_api.run_stream.progress_payload``); a terminal row carries a different topic and is
    filtered out before its shape matters.

    Two filters, tried in order. The named one first — ``_FORWARDED_DESIGN_EVENTS`` stays the
    authority on which *named* events cross the seam. Then rung B's shape filter, which keys on
    the presence of a non-empty ``operations`` list rather than on the event's name: today that
    is exactly ``dsl_compiled`` and ``asset_placed``, and a third op-bearing event added by the
    design runtime tomorrow streams with no edit here. (A checkpoint mark cannot be caught by
    it: its ``operations`` is a COUNT, not a list.)
    """

    if row.topic != _DESIGN_PROGRESS_TOPIC:
        return None
    payload = row.payload if isinstance(row.payload, dict) else {}
    data = payload.get("data")
    if not isinstance(data, dict):
        data = {}
    mapping = _FORWARDED_DESIGN_EVENTS.get(str(payload.get("event_type")))
    if mapping is not None:
        event_type, keys = mapping
        return event_type, {key: data[key] for key in keys if key in data}
    return _op_batch_frame(data, document_id=document_id)


def _op_batch_frame(
    data: dict[str, Any], *, document_id: str | None
) -> tuple[TurnEventType, dict[str, JsonValue]] | None:
    """One ``design.op_batch`` frame for an op-bearing event, or ``None``.

    ``None`` for anything that did not apply operations, and for a leg with no pinned document —
    an op batch is an edit to a document, and naming none would be a frame no consumer can route.
    Otherwise the batch, the ledger position it ends at, and the iteration that produced it, in
    the same never-invent-a-key discipline the mapped frames follow: a key task 6's sink did not
    push is simply absent.
    """

    operations = data.get("operations")
    if not isinstance(operations, list) or not operations or document_id is None:
        return None
    frame: dict[str, JsonValue] = {"document_id": document_id}
    frame.update({key: data[key] for key in _OP_BATCH_KEYS if key in data})
    if len(serialize_value_json(operations).encode()) > _MAX_OPERATIONS_BYTES:
        del frame["operations"]
    return TurnEventType.DESIGN_OP_BATCH, frame


#: One export, one consumer. The underscore is kept from the move: the class is package-internal
#: machinery whose lifecycle ``InlineDesignLaneDriver`` owns, not a seam anything else may hold.
__all__ = ["_DesignEventForwarder"]
