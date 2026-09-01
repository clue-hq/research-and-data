"""Scene live-streaming rung A, Task 2 — a design run's mid-run checkpoints reach the chat.

The design agent has committed its work-in-progress mid-run since P0.4: each verified authoring
round writes the scene through the governed tool and marks the commit with one
``scene_checkpoint_committed`` event on the design run's slice of the platform ``run_event``
outbox. Nothing carried those marks onto the *thread*, so a marketer watching a design turn saw
a spinner for minutes while the document underneath them advanced version by version.

This file pins the bridge: while :class:`~clue_api.design_fleet.InlineDesignLaneDriver` drives a
leg turn, it tails that run's outbox rows and forwards every checkpoint mark onto the leg's turn
stream as one ``design.checkpoint`` frame.

Four properties, one per test:

* **Live and ordered.** Two checkpoints become exactly two frames, in event order, with the
  mapped payload — and the first frame is observable *while the handler is still running*, which
  is the whole point (a drain at the end would stream nothing).
* **Only checkpoints.** The design vocabulary is ~60 event names wide; every other one is
  ordinary run progress and must not become a chat frame.
* **Best-effort.** A forwarder that cannot read the outbox costs frames and nothing else: the
  drive still reaches a terminal run, and the turn's own lifecycle frames are untouched.
* **Fenced writers never appear.** Generation fencing is enforced at the *emit* site
  (``lumen_api.run_stream.fenced_emit``), so a superseded attempt's checkpoint never becomes a
  row at all — and therefore can never be forwarded. The run_event outbox carries no generation
  column, so this is the only place the property can be asserted honestly.

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

from clue_api import design_fleet
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


async def _seed_leg_run(label: str) -> _Seeds:
    """Workspace + project + thread + a queued design run whose envelope names the leg turn.

    The ``config['leg']`` block is exactly what ``DesignLegTurnRunner._envelope`` freezes onto a
    real leg turn's envelope — that frozen block IS the turn identity the forwarder announces
    under, so seeding anything else here would prove nothing about production.
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
            document_id=None,
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
                assert driver.checkpoints_forwarded == 2
            finally:
                await _cleanup(seeds)

    run_async(scenario())


def test_ordinary_design_progress_never_becomes_a_chat_frame() -> None:
    """The design vocabulary is open and wide; only the checkpoint mark crosses the seam."""

    async def scenario() -> None:
        async with db_lifespan():
            seeds = await _seed_leg_run("filter")
            try:
                handler = _EmittingHandler(
                    seeds=seeds,
                    events=(
                        ("dsl_compiled", {"document_id": _DOCUMENT_ID, "version": 2}),
                        ("reviewer_verdict", {"verdict": "accepted"}),
                    ),
                )
                await asyncio.wait_for(
                    _driver(handler).drive(envelope=seeds.envelope), timeout=30.0
                )
                assert await _checkpoint_frames(seeds) == ()
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

                monkeypatch.setattr(design_fleet, "list_run_events", _explode)
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
