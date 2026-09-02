"""Scene live-streaming rungs A and B — a design run's mid-run progress reaches the chat.

The design agent has committed its work-in-progress mid-run since P0.4: each verified authoring
round writes the scene through the governed tool and marks the commit with one
``scene_checkpoint_committed`` event on the design run's slice of the platform ``run_event``
outbox. Nothing carried those marks onto the *thread*, so a marketer watching a design turn saw
a spinner for minutes while the document underneath them advanced version by version.

This file pins the bridge: while :class:`~clue_api.design_fleet.InlineDesignLaneDriver` drives a
leg turn, it tails that run's outbox rows and forwards each of them onto the leg's turn stream —
a checkpoint mark as one ``design.checkpoint`` frame (rung A, task 2), and each op-BEARING
mutation between the checkpoints as one ``design.op_batch`` frame (rung B, task 7).

Rung A's four properties, one per test:

* **Live and ordered.** Two checkpoints become exactly two frames, in event order, with the
  mapped payload — and the first frame is observable *while the handler is still running*, which
  is the whole point (a drain at the end would stream nothing).
* **Only what the seam admits.** The design vocabulary is ~60 event names wide; every other one
  is ordinary run progress and must not become a chat frame.
* **Best-effort.** A forwarder that cannot read the outbox costs frames and nothing else: the
  drive still reaches a terminal run, and the turn's own lifecycle frames are untouched.
* **Fenced writers never appear.** Generation fencing is enforced at the *emit* site
  (``lumen_api.run_stream.fenced_emit``), so a superseded attempt's checkpoint never becomes a
  row at all — and therefore can never be forwarded. The run_event outbox carries no generation
  column, so this is the only place the property can be asserted honestly.

Rung B's four, at the bottom of the file:

* **Batch and position.** An op-bearing event forwards its operations, the ledger position the
  batch ends at, the iteration that produced it, and the leg's document.
* **Never truncated.** A batch too large to carry forwards position-only; half an operation list
  applied to a canvas is a corrupted document.
* **One order.** Op frames and checkpoint frames interleave exactly as the outbox holds them,
  because they report positions in the same operation ledger.
* **No document, no op frames.** A checkpoint names its own document; an op batch does not, so a
  document-less leg streams checkpoints and nothing else.

Driven at the driver seam against a real database, real leases and the real emit path, for the
same reason the neighbouring D5/P3.4 lane tests are: what needs proving is the tail-while-driving
machinery, which HTTP would only obscure. Rows are committed (the tail genuinely polls on its own
connections while the handler runs, which a shared savepoint connection cannot serve) and cleaned
up in a ``finally``.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from lumen_api import run_stream
from sqlalchemy import text

from clue_api import design_event_forwarder
from clue_api.chat.turn_events import (
    TurnEventRow,
    TurnEventType,
    emit_turn_event,
    list_turn_events,
)
from clue_api.design_fleet import InlineDesignLaneDriver
from clue_db import db_lifespan, transaction
from clue_design import runs as design_runs
from clue_design.enums import DesignRunKind
from clue_design.envelopes import DesignTurnEnvelope
from clue_design.errors import DesignRunFencedError
from clue_fleet.work_worker import WorkContext, WorkResult
from tests._workspace import seed_project
from tests.design.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_design_db")

#: The design runtime's own name for a committed P0.4 checkpoint
#: (``lumen_api.main.SCENE_CHECKPOINT_EVENT``).
_SCENE_CHECKPOINT_EVENT = "scene_checkpoint_committed"

#: The document the seeded turn pretends to edit. Never inserted as a ``design_document`` row —
#: the checkpoint payload carries the id by value and nothing in this path dereferences it.
_DOCUMENT_ID = "doc_checkpoint_probe"


class _Seeds:
    """One seeded leg turn: the workspace/project/thread it lives on, plus its design run."""

    def __init__(self, *, envelope: DesignTurnEnvelope, turn_id: UUID, thread_id: str) -> None:
        self.envelope = envelope
        self.turn_id = turn_id
        self.thread_id = thread_id

    @property
    def workspace_id(self) -> str:
        return self.envelope.workspace_id

    @property
    def run_id(self) -> str:
        return self.envelope.run_id


async def _seed_leg_run(label: str, *, document_id: str | None = None) -> _Seeds:
    """Workspace + project + thread + a queued design run whose envelope names the leg turn.

    The ``config['leg']`` block is exactly what ``DesignLegTurnRunner._envelope`` freezes onto a
    real leg turn's envelope — that frozen block IS the turn identity the forwarder announces
    under, so seeding anything else here would prove nothing about production.

    ``document_id`` is the leg's pin, frozen onto the envelope by that same runner
    (``document_id=leg.get("document_id")``). Rung B's op frames name it, because an op batch —
    unlike a checkpoint — carries no document of its own. The design run ROW keeps a null
    document (its column has a real foreign key and this suite inserts no ``design_document``),
    exactly as the by-value checkpoint payload does.
    """

    workspace_id = f"ws_ckpt_{label}_{uuid4().hex[:8]}"
    thread_id = f"thr_ckpt_{label}_{uuid4().hex[:8]}"
    run_id = f"run_{uuid4().hex}"
    turn_id = uuid4()
    async with transaction() as conn:
        project = await seed_project(conn, workspace_id, name=f"Checkpoint {label}")
        await conn.execute(
            text(
                "INSERT INTO agent_thread (id, workspace_id, project_id) "
                "VALUES (:id, :ws, :project)"
            ),
            {"id": thread_id, "ws": workspace_id, "project": project.project_id},
        )
        envelope = DesignTurnEnvelope(
            kind="agent_turn",
            work_id=design_runs.work_id_for_run(run_id),
            workspace_id=workspace_id,
            run_id=run_id,
            checkpoint_thread_id=run_id,
            document_id=document_id,
            config={
                "request": {"prompt": "checkpoint probe", "scene": {}},
                "leg": {
                    "leg_id": str(uuid4()),
                    "thread_id": thread_id,
                    "agent_turn_id": str(turn_id),
                    "execution_id": str(uuid4()),
                },
            },
        )
        await design_runs.create_run(
            conn,
            workspace_id=workspace_id,
            run_id=run_id,
            document_id=None,
            kind=DesignRunKind.AGENT_TURN,
            payload=envelope.model_dump(mode="json"),
            work_id=envelope.work_id,
        )
    return _Seeds(envelope=envelope, turn_id=turn_id, thread_id=thread_id)


async def _cleanup(seeds: _Seeds) -> None:
    async with transaction() as conn:
        for statement, params in (
            ("DELETE FROM work_lease WHERE work_id = :work", {"work": seeds.envelope.work_id}),
            (
                "DELETE FROM run_event WHERE workspace_id = :ws",
                {"ws": seeds.workspace_id},
            ),
            (
                "DELETE FROM agent_turn_event_stream WHERE workspace_id = :ws",
                {"ws": seeds.workspace_id},
            ),
            (
                "DELETE FROM design_agent_run WHERE workspace_id = :ws",
                {"ws": seeds.workspace_id},
            ),
            ("DELETE FROM agent_thread WHERE workspace_id = :ws", {"ws": seeds.workspace_id}),
            ("DELETE FROM project WHERE workspace_id = :ws", {"ws": seeds.workspace_id}),
            ("DELETE FROM brand WHERE workspace_id = :ws", {"ws": seeds.workspace_id}),
            ("DELETE FROM workspace WHERE workspace_id = :ws", {"ws": seeds.workspace_id}),
        ):
            await conn.execute(text(statement), params)


async def _checkpoint_frames(seeds: _Seeds) -> tuple[TurnEventRow, ...]:
    """Every ``design.checkpoint`` frame on this turn, in stream order."""

    async with transaction() as conn:
        rows = await list_turn_events(conn, workspace_id=seeds.workspace_id, turn_id=seeds.turn_id)
    return tuple(row for row in rows if row.event_type == TurnEventType.DESIGN_CHECKPOINT.value)


async def _op_batch_frames(seeds: _Seeds) -> tuple[TurnEventRow, ...]:
    """Every ``design.op_batch`` frame on this turn, in stream order."""

    async with transaction() as conn:
        rows = await list_turn_events(conn, workspace_id=seeds.workspace_id, turn_id=seeds.turn_id)
    return tuple(row for row in rows if row.event_type == TurnEventType.DESIGN_OP_BATCH.value)


async def _design_frames(seeds: _Seeds) -> tuple[TurnEventRow, ...]:
    """Both design frame kinds, interleaved exactly as the stream carries them."""

    design = {TurnEventType.DESIGN_CHECKPOINT.value, TurnEventType.DESIGN_OP_BATCH.value}
    async with transaction() as conn:
        rows = await list_turn_events(conn, workspace_id=seeds.workspace_id, turn_id=seeds.turn_id)
    return tuple(row for row in rows if row.event_type in design)


async def _progress_rows(seeds: _Seeds) -> int:
    """How many PROGRESS rows this run actually left on the outbox (the terminal row rides a
    different topic and is excluded). The guard that makes a "nothing was forwarded" assertion
    mean "the filter refused them" rather than "nothing ever arrived to refuse"."""

    async with transaction() as conn:
        return int(
            (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM run_event WHERE workspace_id = :ws "
                        "AND subject_id = :run AND topic = 'design.run.event'"
                    ),
                    {"ws": seeds.workspace_id, "run": seeds.run_id},
                )
            ).scalar_one()
        )


async def _all_frames(seeds: _Seeds) -> tuple[str, ...]:
    async with transaction() as conn:
        rows = await list_turn_events(conn, workspace_id=seeds.workspace_id, turn_id=seeds.turn_id)
    return tuple(row.event_type for row in rows)


def _driver(handler: Any, **overrides: Any) -> InlineDesignLaneDriver:
    settings: dict[str, Any] = {
        "lease_ttl": timedelta(seconds=6.0),
        "heartbeat_interval_s": 2.0,
        "join_poll_interval_s": 0.1,
        "join_timeout_s": 20.0,
        "checkpoint_poll_interval_s": 0.05,
    }
    settings.update(overrides)
    return InlineDesignLaneDriver(handler=handler, **settings)


class _EmittingHandler:
    """A design turn that writes run events through the real emit path, then finishes.

    ``settle_s`` is the pause after each event: long enough for the lane's tail to poll at least
    once, which is what makes "the frame arrived MID-RUN" an assertion rather than a hope.
    """

    def __init__(
        self,
        *,
        seeds: _Seeds,
        events: tuple[tuple[str, dict[str, Any]], ...],
        settle_s: float = 0.5,
    ) -> None:
        self._seeds = seeds
        self._events = events
        self._settle_s = settle_s
        #: How many checkpoint frames existed on the thread right after the FIRST event settled.
        self.frames_after_first_event = -1
        #: Fence refusals the turn body observed (the zombie-fence case).
        self.fenced: list[DesignRunFencedError] = []

    async def handle(self, context: WorkContext) -> WorkResult:
        workspace_id = str(context.payload["workspace_id"])
        run_id = str(context.payload["run_id"])
        for index, (event_type, data) in enumerate(self._events):
            try:
                async with transaction() as conn:
                    await run_stream.emit_progress(
                        conn,
                        workspace_id=workspace_id,
                        run_id=run_id,
                        event_type=event_type,
                        data=data,
                        expected_generation=int(context.lease_generation),
                    )
            except DesignRunFencedError as error:
                self.fenced.append(error)
            await asyncio.sleep(self._settle_s)
            if index == 0:
                self.frames_after_first_event = len(await _checkpoint_frames(self._seeds))
        async with transaction() as conn:
            await run_stream.complete_run_and_emit(
                conn,
                workspace_id=workspace_id,
                run_id=run_id,
                status="succeeded",
                result={"schema_version": 1, "status": "accepted"},
                event_type="run_completed",
            )
        return WorkResult(outcome="succeeded", references={})


def _checkpoint(*, version: int, operations: int, preflight_clean: bool) -> dict[str, Any]:
    """The design runtime's own checkpoint payload — including the ``reason`` the frame drops."""

    return {
        "document_id": _DOCUMENT_ID,
        "version": version,
        "operations": operations,
        "reason": "authoring_round",
        "preflight_clean": preflight_clean,
    }


def _sink_push(
    *, iteration: int, operations: list[Any], total: int | None = None
) -> dict[str, Any]:
    """The design runtime's own op-bearing sink payload.

    The five base summary fields every ``event_sink`` push carries
    (``lumen_agent.tools.substrate``), plus task 6's ``sink_extra`` pair. The frame keeps four of
    the seven: the summaries are the design run's own stream's business, not the chat's.
    ``total`` defaults to the batch's own length (a run whose whole ledger is this batch)."""

    return {
        "actor": "author",
        "iteration": iteration,
        "input_summary": "compile 1 block",
        "output_summary": "ok",
        "diagnostic_count": 0,
        "operations": operations,
        "operations_total": len(operations) if total is None else total,
    }


def test_mid_run_checkpoints_stream_onto_the_threads_turn_events() -> None:
    """Two committed checkpoints become two ordered ``design.checkpoint`` frames — the first
    of them while the design turn is still running, which is what "live" means here."""

    async def scenario() -> None:
        async with db_lifespan():
            seeds = await _seed_leg_run("stream")
            try:
                handler = _EmittingHandler(
                    seeds=seeds,
                    events=(
                        (
                            _SCENE_CHECKPOINT_EVENT,
                            _checkpoint(version=3, operations=3, preflight_clean=True),
                        ),
                        (
                            _SCENE_CHECKPOINT_EVENT,
                            _checkpoint(version=7, operations=7, preflight_clean=False),
                        ),
                    ),
                )
                driver = _driver(handler)
                await asyncio.wait_for(driver.drive(envelope=seeds.envelope), timeout=30.0)
                frames = await _checkpoint_frames(seeds)
                assert [frame.payload for frame in frames] == [
                    {
                        "document_id": _DOCUMENT_ID,
                        "version": 3,
                        "operations": 3,
                        "preflight_clean": True,
                    },
                    {
                        "document_id": _DOCUMENT_ID,
                        "version": 7,
                        "operations": 7,
                        "preflight_clean": False,
                    },
                ]
                # Announced on the leg's own thread and project, under the leg turn.
                for frame in frames:
                    assert frame.thread_id == seeds.thread_id
                    assert frame.turn_id == seeds.turn_id
                assert handler.frames_after_first_event == 1, (
                    "the first checkpoint reached the thread only after the run finished — "
                    "the tail is draining, not streaming"
                )
                # Each row forwarded exactly once for this attempt: the tail polls many times
                # over the turn, and a cursor-less re-read would show up here as a re-send.
                assert driver.frames_forwarded == 2
            finally:
                await _cleanup(seeds)

    run_async(scenario())


def test_ordinary_design_progress_never_becomes_a_chat_frame() -> None:
    """The design vocabulary is open and wide; only a checkpoint mark or an op-BEARING event
    crosses the seam.

    Rung B widened the seam by *shape*, not by name: an event forwards as ``design.op_batch``
    when it carries a non-empty ``operations`` list. So the three events here are the three ways
    to miss — a mutation event with no ops at all, one whose batch is empty, and an event that
    never had ops to begin with. The outbox row count is asserted first so "no frames" can only
    mean "the filter refused them", never "the emits silently failed" (task 2 minor)."""

    async def scenario() -> None:
        async with db_lifespan():
            seeds = await _seed_leg_run("filter", document_id=_DOCUMENT_ID)
            try:
                handler = _EmittingHandler(
                    seeds=seeds,
                    events=(
                        ("dsl_compiled", {"document_id": _DOCUMENT_ID, "version": 2}),
                        ("asset_placed", _sink_push(iteration=4, operations=[])),
                        ("reviewer_verdict", {"verdict": "accepted"}),
                    ),
                )
                await asyncio.wait_for(
                    _driver(handler).drive(envelope=seeds.envelope), timeout=30.0
                )
                assert await _progress_rows(seeds) == 3, (
                    "the seeded events never reached the outbox — this test would pass vacuously"
                )
                assert await _checkpoint_frames(seeds) == ()
                assert await _op_batch_frames(seeds) == ()
                assert await _all_frames(seeds) == ()
            finally:
                await _cleanup(seeds)

    run_async(scenario())


def test_a_forwarder_failure_costs_frames_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A forwarder that cannot read the outbox must never fail or stall the drive, and must
    leave the turn's own lifecycle frames exactly as it found them."""

    async def scenario() -> None:
        async with db_lifespan():
            seeds = await _seed_leg_run("besteffort")
            try:
                # A pre-existing lifecycle frame, so "untouched" is observable rather than
                # vacuous.
                async with transaction() as conn:
                    await emit_turn_event(
                        conn,
                        workspace_id=seeds.workspace_id,
                        project_id=(
                            await conn.execute(
                                text(
                                    "SELECT project_id FROM agent_thread "
                                    "WHERE id = :t AND workspace_id = :ws"
                                ),
                                {"t": seeds.thread_id, "ws": seeds.workspace_id},
                            )
                        ).scalar_one(),
                        thread_id=seeds.thread_id,
                        turn_id=seeds.turn_id,
                        event_type=TurnEventType.TURN_STARTED,
                    )

                async def _explode(*args: Any, **kwargs: Any) -> Any:
                    raise RuntimeError("the outbox read failed")

                monkeypatch.setattr(design_event_forwarder, "list_run_events", _explode)
                handler = _EmittingHandler(
                    seeds=seeds,
                    events=(
                        (
                            _SCENE_CHECKPOINT_EVENT,
                            _checkpoint(version=1, operations=1, preflight_clean=True),
                        ),
                    ),
                )
                await asyncio.wait_for(
                    _driver(handler).drive(envelope=seeds.envelope), timeout=30.0
                )
                async with transaction() as conn:
                    run = await design_runs.get_run(
                        conn, workspace_id=seeds.workspace_id, run_id=seeds.run_id
                    )
                assert run is not None and run["status"] == "succeeded"
                assert await _checkpoint_frames(seeds) == ()
                assert await _all_frames(seeds) == (TurnEventType.TURN_STARTED.value,)
            finally:
                await _cleanup(seeds)

    run_async(scenario())


def test_a_fenced_attempts_checkpoint_never_reaches_the_thread() -> None:
    """The zombie fence is enforced where the row is written, so a superseded attempt's
    checkpoint is never a row — and a reader can therefore never forward one."""

    async def scenario() -> None:
        async with db_lifespan():
            seeds = await _seed_leg_run("fenced")
            try:
                # A takeover has already claimed this run at a HIGHER generation than the
                # lane's handler will hold (an inline lane's context generation starts at 1).
                async with transaction() as conn:
                    await conn.execute(
                        text(
                            "UPDATE design_agent_run SET lease_generation = 99, "
                            "leased_by = 'takeover-worker', leased_at = now() "
                            "WHERE run_id = :r AND workspace_id = :ws"
                        ),
                        {"r": seeds.run_id, "ws": seeds.workspace_id},
                    )
                handler = _EmittingHandler(
                    seeds=seeds,
                    events=(
                        (
                            _SCENE_CHECKPOINT_EVENT,
                            _checkpoint(version=4, operations=4, preflight_clean=True),
                        ),
                    ),
                )
                await asyncio.wait_for(
                    _driver(handler).drive(envelope=seeds.envelope), timeout=30.0
                )
                assert handler.fenced, "the stale-generation emit was not fenced at all"
                async with transaction() as conn:
                    stored = (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM run_event WHERE workspace_id = :ws "
                                "AND payload ->> 'event_type' = :event"
                            ),
                            {"ws": seeds.workspace_id, "event": _SCENE_CHECKPOINT_EVENT},
                        )
                    ).scalar_one()
                assert stored == 0, "a fenced writer left a checkpoint row behind"
                assert await _checkpoint_frames(seeds) == ()
            finally:
                await _cleanup(seeds)

    run_async(scenario())


# --- rung B: the per-mutation operation batches -----------------------------------------------


def test_op_bearing_design_events_stream_their_batch_and_ledger_position() -> None:
    """Every op-bearing mutation becomes one ``design.op_batch`` frame carrying the batch, the
    ledger position it ends at, the iteration that produced it, and the leg's document.

    Keyed on the SHAPE of the event, not its name: ``dsl_compiled`` and ``asset_placed`` are
    merely today's two op-bearing events, and a third would stream with no code change here."""

    async def scenario() -> None:
        async with db_lifespan():
            seeds = await _seed_leg_run("ops", document_id=_DOCUMENT_ID)
            try:
                compiled = [{"kind": "add_page"}, {"kind": "insert_node"}]
                placed = [{"kind": "set_fill", "node": "hero"}]
                handler = _EmittingHandler(
                    seeds=seeds,
                    events=(
                        ("dsl_compiled", _sink_push(iteration=1, operations=compiled)),
                        (
                            "asset_placed",
                            _sink_push(iteration=2, operations=placed, total=3),
                        ),
                    ),
                )
                driver = _driver(handler)
                await asyncio.wait_for(driver.drive(envelope=seeds.envelope), timeout=30.0)
                frames = await _op_batch_frames(seeds)
                assert [frame.payload for frame in frames] == [
                    {
                        "document_id": _DOCUMENT_ID,
                        "operations": compiled,
                        "operations_total": 2,
                        "iteration": 1,
                    },
                    {
                        "document_id": _DOCUMENT_ID,
                        "operations": placed,
                        "operations_total": 3,
                        "iteration": 2,
                    },
                ]
                # The document comes from the LEG's pin, which is the only place an op batch
                # could get one: the runtime's op events name no document at all.
                assert "document_id" not in _sink_push(iteration=1, operations=compiled)
                for frame in frames:
                    assert frame.thread_id == seeds.thread_id
                    assert frame.turn_id == seeds.turn_id
                assert driver.frames_forwarded == 2

            finally:
                await _cleanup(seeds)

    run_async(scenario())


def test_an_oversize_batch_forwards_its_position_and_never_a_truncated_batch() -> None:
    """A batch too large for a chat frame streams position-only.

    Truncation is not on the table: half an operation list applied to a canvas is a corrupted
    document, whereas a position with no operations is honest — the client simply waits for the
    next checkpoint and reloads. The neighbouring small batch proves the cut is per-batch."""

    async def scenario() -> None:
        async with db_lifespan():
            seeds = await _seed_leg_run("oversize", document_id=_DOCUMENT_ID)
            try:
                huge = [{"kind": "set_text", "text": "x" * 300_000}]
                small = [{"kind": "set_fill", "node": "hero"}]
                handler = _EmittingHandler(
                    seeds=seeds,
                    events=(
                        ("dsl_compiled", _sink_push(iteration=1, operations=huge, total=9)),
                        ("asset_placed", _sink_push(iteration=2, operations=small, total=10)),
                    ),
                )
                await asyncio.wait_for(
                    _driver(handler).drive(envelope=seeds.envelope), timeout=30.0
                )
                frames = await _op_batch_frames(seeds)
                assert [frame.payload for frame in frames] == [
                    {"document_id": _DOCUMENT_ID, "operations_total": 9, "iteration": 1},
                    {
                        "document_id": _DOCUMENT_ID,
                        "operations": small,
                        "operations_total": 10,
                        "iteration": 2,
                    },
                ]
            finally:
                await _cleanup(seeds)

    run_async(scenario())


def test_op_batches_and_checkpoints_interleave_in_outbox_order() -> None:
    """One tail, one cursor, one order. The two frame kinds describe positions in the SAME
    operation ledger, so a consumer can only reconcile them if the stream preserves the order
    the design run wrote them in."""

    async def scenario() -> None:
        async with db_lifespan():
            seeds = await _seed_leg_run("interleave", document_id=_DOCUMENT_ID)
            try:
                first = [{"kind": "add_page"}, {"kind": "insert_node"}]
                second = [{"kind": "set_text"}]
                handler = _EmittingHandler(
                    seeds=seeds,
                    events=(
                        ("dsl_compiled", _sink_push(iteration=1, operations=first, total=2)),
                        (
                            _SCENE_CHECKPOINT_EVENT,
                            _checkpoint(version=2, operations=2, preflight_clean=True),
                        ),
                        ("dsl_compiled", _sink_push(iteration=2, operations=second, total=3)),
                        (
                            _SCENE_CHECKPOINT_EVENT,
                            _checkpoint(version=3, operations=3, preflight_clean=True),
                        ),
                    ),
                    settle_s=0.3,
                )
                await asyncio.wait_for(
                    _driver(handler).drive(envelope=seeds.envelope), timeout=40.0
                )
                frames = await _design_frames(seeds)
                assert [frame.event_type for frame in frames] == [
                    TurnEventType.DESIGN_OP_BATCH.value,
                    TurnEventType.DESIGN_CHECKPOINT.value,
                    TurnEventType.DESIGN_OP_BATCH.value,
                    TurnEventType.DESIGN_CHECKPOINT.value,
                ]
                # Each op batch is followed by the checkpoint that made it durable: the batch
                # ending at ledger position N, then the checkpoint reporting N committed.
                assert [frame.payload.get("operations_total") for frame in frames] == [
                    2,
                    None,
                    3,
                    None,
                ]
                assert [frame.payload.get("version") for frame in frames] == [None, 2, None, 3]
            finally:
                await _cleanup(seeds)

    run_async(scenario())


def test_a_document_less_leg_forwards_checkpoints_but_no_op_batches() -> None:
    """An op batch is an edit to a document, and it carries none of its own.

    A leg with no pinned document (a legacy leg, a preview-only turn) therefore streams no op
    frames at all rather than one naming ``null``, which no consumer could route to a canvas.
    Checkpoint frames are unaffected — the mark names its own document — and that contrast is
    what makes this the *op* frame's rule rather than a general silence."""

    async def scenario() -> None:
        async with db_lifespan():
            seeds = await _seed_leg_run("nodoc")
            assert seeds.envelope.document_id is None
            try:
                handler = _EmittingHandler(
                    seeds=seeds,
                    events=(
                        (
                            "dsl_compiled",
                            _sink_push(iteration=1, operations=[{"kind": "add_page"}]),
                        ),
                        (
                            _SCENE_CHECKPOINT_EVENT,
                            _checkpoint(version=1, operations=1, preflight_clean=True),
                        ),
                    ),
                )
                await asyncio.wait_for(
                    _driver(handler).drive(envelope=seeds.envelope), timeout=30.0
                )
                assert await _progress_rows(seeds) == 2, (
                    "the seeded events never reached the outbox — this test would pass vacuously"
                )
                assert await _op_batch_frames(seeds) == ()
                assert len(await _checkpoint_frames(seeds)) == 1
            finally:
                await _cleanup(seeds)

    run_async(scenario())
