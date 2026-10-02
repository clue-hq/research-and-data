"""D5 Round B acceptance: design turns as leased, recoverable fleet work.

The slice's whole claim is that a design turn survives the death of the process running it. This
file is the proof, end to end against a real database, a real fleet queue, and real leases:

* **kill-and-resume.** Worker A claims a turn (run goes ``running``, stamped with A's id and lease
  generation) and blocks mid-turn. A dies without finishing. Worker B, arriving after the lease
  expires, re-claims the SAME run at a higher generation through the D5 CAS and finishes it. The
  run reaches a terminal status exactly once, and its event stream stays coherent — one terminal
  event, and it is the last.
* **the zombie fence.** A's turn body is a synchronous thread that cannot be cancelled, so it is
  still running after A is gone and eventually tries to write its own terminal result. That write
  is refused by the generation fence: B's result survives untouched. This is the specific hazard
  the design row's ``expected_generation`` guard exists for.
* **concurrency.** Two turns in two different workspaces drain without one blocking the other's
  claim.

Deliberately driven at the WORKER seam rather than over HTTP: the API's contribution (offer the
run + its task in one transaction) is asserted in the design API suite, whereas what needs proving
here is the claim/fence/takeover machinery, which HTTP would only obscure.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from lumen_api import run_stream
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import ProjectRunId
from clue_db import db_lifespan, transaction
from clue_design import runs as design_runs
from clue_design.enums import DesignRunKind
from clue_design.envelopes import DesignTurnEnvelope
from clue_design.errors import DesignRunFencedError
from clue_fleet.enums import FleetTaskKind
from clue_fleet.lease import DbWorkLeaseStore, LeaseGeneration, WorkId, WorkLeaseRow
from clue_fleet.queue import enqueue_task
from clue_fleet.work_worker import LeasedWorkWorker
from tests.design.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_design_db")

# Short enough that a killed worker's lease expires inside a test, long enough that the
# construction invariant (2 * heartbeat < ttl) holds and a live worker is never fenced by accident.
_LEASE_TTL = timedelta(seconds=2)
_HEARTBEAT = 0.5
_STALE_AFTER = timedelta(seconds=2)
_POLL = 0.05


def _minimal_turn_request(prompt: str) -> dict[str, Any]:
    """The smallest body ``AgentTurnPreviewRequest`` accepts — the envelope's ``config.request``."""
    return {
        "prompt": prompt,
        "scene": {"id": "scene_test", "schema_version": 1, "pages": [], "assets": {}},
        "diagnostics": [],
    }


async def _seed_workspace(conn: AsyncConnection, tag: str) -> str:
    workspace_id = f"ws_test_{tag}_{uuid4().hex[:10]}"
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": workspace_id}
    )
    return workspace_id


async def _offer_turn(workspace_id: str, prompt: str) -> tuple[str, UUID]:
    """Create a queued run and offer its ``design_job`` — the API's one transaction, in
    miniature."""
    run_id = f"run_{uuid4().hex}"
    work_id = design_runs.work_id_for_run(run_id)
    envelope = DesignTurnEnvelope(
        work_id=work_id,
        workspace_id=workspace_id,
        kind="agent_turn",
        run_id=run_id,
        checkpoint_thread_id=run_id,
        document_id=None,
        config={"request": _minimal_turn_request(prompt), "reference_assets": None},
    ).model_dump(mode="json")
    async with transaction() as conn:
        await design_runs.create_run(
            conn,
            workspace_id=workspace_id,
            run_id=run_id,
            document_id=None,
            kind=DesignRunKind.AGENT_TURN,
            payload=envelope,
            work_id=work_id,
        )
        await enqueue_task(
            conn,
            kind=FleetTaskKind.DESIGN_JOB,
            project_run_id=ProjectRunId(work_id),
            dedup_key=str(work_id),
            payload=envelope,
        )
    return run_id, work_id


async def _read_run(workspace_id: str, run_id: str) -> dict[str, Any]:
    async with transaction() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT status, leased_by, lease_generation, result_json"
                    " FROM design_agent_run WHERE run_id = :r AND workspace_id = :w"
                ),
                {"r": run_id, "w": workspace_id},
            )
        ).one()
    return {
        "status": row.status,
        "leased_by": row.leased_by,
        "lease_generation": row.lease_generation,
        "result": row.result_json,
    }


async def _read_events(workspace_id: str, run_id: str) -> list[dict[str, Any]]:
    """The run's stream in the editor's row shape — since D7 that is the platform ``run_event``
    outbox filtered to this run's subject, read back through the same mapper the SSE route uses."""
    async with transaction() as conn:
        return await run_stream.run_snapshot_events(conn, workspace_id=workspace_id, run_id=run_id)


async def _await_condition(probe: Any, *, timeout: float = 15.0, label: str = "") -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = await probe()
        if value is not None:
            return value
        await asyncio.sleep(0.05)
    raise AssertionError(f"condition never held within {timeout}s: {label}")


def _build_worker(handler: Any, worker_id: str, *, leases: Any = None) -> LeasedWorkWorker:
    return LeasedWorkWorker(
        handlers=(handler,),
        leases=leases,
        worker_id=worker_id,
        poll_interval=_POLL,
        lease_ttl=_LEASE_TTL,
        heartbeat_interval=_HEARTBEAT,
        task_stale_after=_STALE_AFTER,
    )


class _KilledWorkerLeases:
    """A lease store that never releases — what a SIGKILLed worker's lease looks like.

    Cancelling a worker task is NOT a faithful death simulation on its own: ``_run_task``'s
    ``finally`` still runs, and a released lease row is deleted, so the next acquire starts back
    at generation 1 and no takeover is observable. A process that is killed outright never gets
    that far — its lease row sits there, held and un-renewed, until it expires and the next
    acquire increments the generation. That increment is the entire fencing mechanism, so the
    test has to reproduce the real shape rather than the tidy one.
    """

    def __init__(self, inner: DbWorkLeaseStore | None = None) -> None:
        self._inner = inner if inner is not None else DbWorkLeaseStore()

    async def acquire(
        self, *, work_id: WorkId, worker_id: str, ttl: timedelta
    ) -> WorkLeaseRow | None:
        return await self._inner.acquire(work_id=work_id, worker_id=worker_id, ttl=ttl)

    async def renew(
        self,
        *,
        work_id: WorkId,
        worker_id: str,
        generation: LeaseGeneration,
        ttl: timedelta,
    ) -> bool:
        return await self._inner.renew(
            work_id=work_id, worker_id=worker_id, generation=generation, ttl=ttl
        )

    async def release(
        self, *, work_id: WorkId, worker_id: str, generation: LeaseGeneration
    ) -> None:
        return None

    async def get(self, work_id: WorkId) -> WorkLeaseRow | None:
        return await self._inner.get(work_id)


class _GatedRunner:
    """A stubbed ``agent_turn_runner``: attempt 1 blocks until released, attempt 2+ returns.

    This is exactly the shape the kill-and-resume scenario needs and nothing more. Attempt 1 is
    the doomed one — it is still inside ``agent.invoke``'s stand-in when its worker dies — and
    attempt 2 is the takeover, which must be able to finish without waiting on the corpse.
    """

    def __init__(self) -> None:
        self.release = threading.Event()
        self.attempt_1_started = threading.Event()
        self.attempt_1_returned = threading.Event()
        self.attempts = 0
        self._lock = threading.Lock()

    def __call__(self, payload: Any, root: Any) -> dict[str, Any]:
        with self._lock:
            self.attempts += 1
            attempt = self.attempts
        if attempt == 1:
            self.attempt_1_started.set()
            self.release.wait(timeout=30)
            self.attempt_1_returned.set()
            return {"schema_version": 1, "status": "proposed", "summary": "zombie attempt"}
        return {"schema_version": 1, "status": "proposed", "summary": f"attempt {attempt}"}


def test_a_killed_worker_is_taken_over_and_its_zombie_write_is_fenced(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from lumen_api.fleet_handler import DesignTurnHost, build_design_job_handler

    caplog.set_level("WARNING", logger="lumen_api.fleet_handler")

    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                workspace_id = await _seed_workspace(conn, "takeover")
            run_id, work_id = await _offer_turn(workspace_id, "design a poster")

            runner = _GatedRunner()
            # No checkpointer: the stub never builds a graph, so a saver would only add a
            # connection per turn. The checkpointer seam itself is covered by the harness tests.
            handler = build_design_job_handler(
                host_provider=lambda: DesignTurnHost(agent_turn_runner=runner),
                checkpointer_factory=None,
            )

            worker_a = _build_worker(handler, "worker-a", leases=_KilledWorkerLeases())
            task_a = asyncio.create_task(worker_a.run())

            async def claimed_by_a() -> dict[str, Any] | None:
                row = await _read_run(workspace_id, run_id)
                claimed = row["status"] == "running" and row["leased_by"] == "worker-a"
                return row if claimed else None

            first = await _await_condition(claimed_by_a, label="worker A claims the run")
            assert first["lease_generation"] == 1

            async def attempt_1_running() -> bool | None:
                return True if runner.attempt_1_started.is_set() else None

            await _await_condition(attempt_1_running, label="A's turn body is mid-flight")
            assert runner.attempts == 1

            # --- A dies mid-turn. Not a graceful stop: the drive is cancelled outright, exactly
            # as a SIGKILL would, so A never releases its lease and never finalizes its task. The
            # synchronous turn thread it started is NOT cancelled (Python cannot) and is still
            # blocked inside the stub — the zombie.
            task_a.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task_a

            # The lease and the claimed task both have to age out before a takeover is legal.
            await asyncio.sleep(_LEASE_TTL.total_seconds() + 0.5)

            worker_b = _build_worker(handler, "worker-b")
            task_b = asyncio.create_task(worker_b.run())
            try:

                async def finished_by_b() -> dict[str, Any] | None:
                    row = await _read_run(workspace_id, run_id)
                    return row if row["status"] in ("succeeded", "failed") else None

                terminal = await _await_condition(finished_by_b, label="worker B finishes the run")
                assert terminal["status"] == "succeeded"
                assert terminal["leased_by"] == "worker-b"
                # Generations are monotonic: B's claim proves A's lease was superseded.
                assert terminal["lease_generation"] > first["lease_generation"]
                assert terminal["result"]["summary"] == "attempt 2"
                assert runner.attempts == 2

                # --- now let the zombie finish. It will try to complete the SAME run under its
                # stale generation, which is precisely the write the fence exists to refuse.
                runner.release.set()
                assert runner.attempt_1_returned.wait(timeout=15)
                # The zombie's terminal write happens just after its runner returns; give it room
                # to land (or, as asserted below, to be refused).
                await asyncio.sleep(2.0)

                after_zombie = await _read_run(workspace_id, run_id)
                assert after_zombie["result"]["summary"] == "attempt 2", (
                    "the fenced-out zombie overwrote the takeover worker's result"
                )
                assert after_zombie["status"] == "succeeded"
                assert after_zombie["leased_by"] == "worker-b"

                # The SSE-visible stream is coherent: exactly one terminal event, and it is last.
                events = await _read_events(workspace_id, run_id)
                terminal_events = [e for e in events if e["type"] in ("result", "error")]
                assert len(terminal_events) == 1, events
                assert events[-1]["type"] == "result"
                assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)

                # And the refusal was OBSERVED, not merely inferred from an unchanged row: the
                # zombie really did attempt its terminal write and the fence really did refuse it.
                fenced = [
                    record
                    for record in caplog.records
                    if "terminal_write_fenced" in str(record.msg)
                ]
                assert fenced, "the zombie's fenced terminal write was never recorded"
                assert any(
                    str(record.msg).find("'lease_generation': 1") >= 0
                    and str(record.msg).find("'current_generation': 2") >= 0
                    for record in fenced
                ), fenced
            finally:
                worker_b.stop()
                task_b.cancel()
                await asyncio.gather(task_b, return_exceptions=True)

    run_async(scenario())


def test_the_generation_fence_refuses_stale_terminal_writes_and_stale_events() -> None:
    """The fence in isolation — the DAL-level statement of what the scenario above proves."""

    async def scenario() -> None:
        async with db_lifespan(), transaction() as conn:
            workspace_id = await _seed_workspace(conn, "fence")
            run_id = f"run_{uuid4().hex}"
            work_id = design_runs.work_id_for_run(run_id)
            await design_runs.create_run(
                conn, workspace_id=workspace_id, run_id=run_id, document_id=None, work_id=work_id
            )
            # A takeover worker owns the run at generation 5.
            claimed = await design_runs.claim_run_for_execution(
                conn, work_id=work_id, worker_id="worker-live", lease_generation=5
            )
            assert claimed is not None

            # The abandoned generation-1 writer is refused on BOTH durable surfaces.
            with pytest.raises(DesignRunFencedError) as terminal_error:
                await run_stream.complete_run_and_emit(
                    conn,
                    workspace_id=workspace_id,
                    run_id=run_id,
                    status="failed",
                    result={"summary": "zombie"},
                    event_type="error",
                    expected_generation=1,
                )
            assert terminal_error.value.expected_generation == 1
            assert terminal_error.value.current_generation == 5

            with pytest.raises(DesignRunFencedError):
                await run_stream.emit_progress(
                    conn,
                    workspace_id=workspace_id,
                    run_id=run_id,
                    event_type="progress",
                    data={"from": "zombie"},
                    expected_generation=1,
                )

            # Refused, not partially applied: no result, no status change, no event. D7 keeps this
            # exact guarantee on the shared outbox — ``fenced_emit`` checks the generation BEFORE
            # it writes, so a fenced-out zombie leaves the stream completely unpolluted.
            run = await design_runs.require_run(conn, workspace_id=workspace_id, run_id=run_id)
            assert run["status"] == "running"
            assert run["result"] is None
            assert (
                await run_stream.run_snapshot_events(conn, workspace_id=workspace_id, run_id=run_id)
                == []
            )

            # The LIVE holder writes through the same fence unimpeded.
            await run_stream.complete_run_and_emit(
                conn,
                workspace_id=workspace_id,
                run_id=run_id,
                status="succeeded",
                result={"summary": "live"},
                event_type="result",
                expected_generation=5,
            )
            done = await design_runs.require_run(conn, workspace_id=workspace_id, run_id=run_id)
            assert done["status"] == "succeeded"
            assert done["result"] == {"summary": "live"}
            await conn.rollback()

    run_async(scenario())


class _CheckpointingRunner:
    """A stub turn body that is a REAL LangGraph graph on the REAL Postgres saver.

    ``_GatedRunner`` above proves the claim/fence/takeover machinery with
    ``checkpointer_factory=None`` — deliberately, because its stub never builds a graph. That
    leaves one production composition no test exercises: the handler's checkpointer seam wired to
    ``postgres_design_checkpointer``, with graph state actually landing in Postgres under the
    turn's ``checkpoint_thread_id`` (the run id for these document-less envelopes; a
    document-pinned leg turn threads on its session id instead). This runner closes that gap.

    Attempt 1 blocks inside the graph's second node — *after* the first superstep's checkpoint has
    been written — and is then abandoned. Attempt 2 (the takeover) reads the thread back through a
    fresh saver, records what it found, and drives the turn through the production
    :func:`~lumen_agent.checkpoint.invoke_turn_graph` seam.
    """

    def __init__(self) -> None:
        self.release = threading.Event()
        self.attempt_1_started = threading.Event()
        self.attempt_1_returned = threading.Event()
        self.attempts = 0
        #: What the TAKEOVER saw on the thread before it did anything to it.
        self.takeover_saw_checkpoint: bool | None = None
        self.takeover_checkpoint_rows: int | None = None
        self._lock = threading.Lock()

    def _graph(self, saver: Any, block: bool) -> Any:
        from langgraph.graph import END, START, StateGraph

        release = self.release

        def _first(state: dict[str, Any]) -> dict[str, Any]:
            return {"steps": [*state["steps"], "first"]}

        def _second(state: dict[str, Any]) -> dict[str, Any]:
            if block:
                # The doomed attempt parks here. The checkpoint for the FIRST superstep is already
                # committed, which is the state the takeover has to be able to see.
                release.wait(timeout=30)
            return {"steps": [*state["steps"], "second"]}

        graph = StateGraph(dict)
        graph.add_node("first", _first)
        graph.add_node("second", _second)
        graph.add_edge(START, "first")
        graph.add_edge("first", "second")
        graph.add_edge("second", END)
        return graph.compile(checkpointer=saver)

    def __call__(self, payload: Any, root: Any) -> dict[str, Any]:
        from lumen_agent.checkpoint import invoke_turn_graph

        saver = _checkpointer_for_this_thread()
        thread_id = _thread_id_for_this_thread()
        config = {"configurable": {"thread_id": thread_id}}
        with self._lock:
            self.attempts += 1
            attempt = self.attempts

        if attempt == 1:
            self.attempt_1_started.set()
            agent = self._graph(saver, block=True)
            agent.invoke({"steps": []}, config=config)
            self.attempt_1_returned.set()
            return {"schema_version": 1, "status": "proposed", "summary": "zombie attempt"}

        # --- the takeover. Look at the thread BEFORE touching it: this is the certification.
        agent = self._graph(saver, block=False)
        snapshot = agent.get_state(config)
        self.takeover_saw_checkpoint = getattr(snapshot, "created_at", None) is not None
        self.takeover_checkpoint_rows = len(list(saver.list(config)))

        # …then drive it through the PRODUCTION seam, which continues the thread it found (see
        # ``lumen_agent/checkpoint.py``: a thread that already carries state is the normal case).
        state = invoke_turn_graph(
            agent,
            {"steps": []},
            invoke_config=config,
            checkpointer=saver,
            thread_id=thread_id,
        )
        return {
            "schema_version": 1,
            "status": "proposed",
            "summary": f"attempt {attempt}",
            "steps": state["steps"],
        }


#: The saver the handler opened for the turn running on THIS thread. Thread-local because the
#: abandoned attempt's thread and the takeover's thread are alive at the same time and each is
#: inside its own ``postgres_design_checkpointer`` context.
_CHECKPOINTER_LOCAL = threading.local()


def _checkpointer_for_this_thread() -> Any:
    saver = getattr(_CHECKPOINTER_LOCAL, "saver", None)
    assert saver is not None, "the handler did not open a checkpointer for this turn"
    return saver


def _thread_id_for_this_thread() -> str:
    thread_id = getattr(_CHECKPOINTER_LOCAL, "thread_id", None)
    assert isinstance(thread_id, str)
    return thread_id


@contextlib.contextmanager
def _publishing_checkpointer(thread_id: str) -> Any:
    """The PRODUCTION factory, with the opened saver published to the turn body.

    ``postgres_design_checkpointer`` is called verbatim — the real sync ``PostgresSaver`` on the
    real platform database, opened inside the turn thread, keyed by the turn's
    ``checkpoint_thread_id`` (see ``_CheckpointingRunner`` on what that id is). The only thing
    added is the publish, which exists because the stub runner seam
    (``DesignTurnHost.agent_turn_runner``) receives ``(payload, root)`` and not the checkpointer
    the real ``run_agent_turn_preview`` is handed.
    """
    from lumen_api.fleet_handler import postgres_design_checkpointer

    with postgres_design_checkpointer(thread_id) as saver:
        _CHECKPOINTER_LOCAL.saver = saver
        _CHECKPOINTER_LOCAL.thread_id = thread_id
        try:
            yield saver
        finally:
            _CHECKPOINTER_LOCAL.saver = None


def test_a_taken_over_run_finds_its_checkpoint_thread_on_the_real_postgres_saver(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Kill-and-resume with the REAL checkpointer composed — the one D5 left unexercised.

    WHAT THIS CERTIFIES, EXACTLY: **checkpoint continuity across a worker death.** The takeover
    worker finds the dead attempt's graph state durably present in Postgres, addressed by the SAME
    ``checkpoint_thread_id``, loadable through a fresh saver on a different worker, and it then
    drives the turn through the production ``invoke_turn_graph`` seam, which CONTINUES that thread
    (session continuity, 2026-09-18) with the frozen envelope's input.

    The thread id here is the run id because these envelopes pin no document. That is the
    document-less shape, not a ruling for every turn: since session continuity a document-pinned
    leg turn threads on its DOCUMENT's session id, so consecutive turns of one design meet on one
    thread.

    WHAT THIS DOES **NOT** CERTIFY: mid-turn resume. Design turns are not resumable — the tool
    substrate (scene, trace dir, ``final.json``) is not in the checkpoint and cannot be
    reconstructed — and ``lumen_agent/checkpoint.py`` documents that as a measured finding, not a
    gap. Continuity here means "the state is there, addressable and readable across a worker
    death", which is what makes the restart *deliberate* rather than accidental.
    """
    from lumen_api.fleet_handler import DesignTurnHost, build_design_job_handler

    # INFO: the seam says which branch it took at info level (continue / resume); only its
    # best-effort failures are warnings.
    caplog.set_level("INFO", logger="lumen_agent.checkpoint")

    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                workspace_id = await _seed_workspace(conn, "ckpt")
            run_id, _work_id = await _offer_turn(workspace_id, "checkpointed poster")

            runner = _CheckpointingRunner()
            handler = build_design_job_handler(
                host_provider=lambda: DesignTurnHost(agent_turn_runner=runner),
                # The REAL production factory, wrapped only so the stub body can reach the saver.
                checkpointer_factory=_publishing_checkpointer,
            )

            worker_a = _build_worker(handler, "worker-ckpt-a", leases=_KilledWorkerLeases())
            task_a = asyncio.create_task(worker_a.run())

            async def claimed_by_a() -> dict[str, Any] | None:
                row = await _read_run(workspace_id, run_id)
                claimed = row["status"] == "running" and row["leased_by"] == "worker-ckpt-a"
                return row if claimed else None

            first = await _await_condition(claimed_by_a, label="worker A claims the run")
            assert first["lease_generation"] == 1

            async def attempt_1_running() -> bool | None:
                return True if runner.attempt_1_started.is_set() else None

            await _await_condition(attempt_1_running, label="A's graph is mid-flight")

            # The first superstep's checkpoint has to be DURABLE before A dies, or the takeover
            # would have nothing to find and this test would pass vacuously.
            async def checkpoint_landed() -> bool | None:
                return True if await _checkpoint_rows(run_id) else None

            await _await_condition(checkpoint_landed, label="A's first checkpoint is committed")

            task_a.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task_a
            await asyncio.sleep(_LEASE_TTL.total_seconds() + 0.5)

            worker_b = _build_worker(handler, "worker-ckpt-b")
            task_b = asyncio.create_task(worker_b.run())
            try:

                async def finished_by_b() -> dict[str, Any] | None:
                    row = await _read_run(workspace_id, run_id)
                    return row if row["status"] in ("succeeded", "failed") else None

                terminal = await _await_condition(finished_by_b, label="worker B finishes the run")
                assert terminal["status"] == "succeeded"
                assert terminal["leased_by"] == "worker-ckpt-b"
                assert terminal["lease_generation"] > first["lease_generation"]
                assert terminal["result"]["summary"] == "attempt 2"
                # The restart really ran the whole graph, not a resumed tail.
                assert terminal["result"]["steps"] == ["first", "second"]

                # THE CERTIFICATION: the takeover, on a different worker at a higher generation,
                # loaded the dead attempt's graph state from Postgres under this run's thread id.
                assert runner.takeover_saw_checkpoint is True, (
                    "the takeover found no graph state on the run's checkpoint thread"
                )
                assert (runner.takeover_checkpoint_rows or 0) >= 1

                # And it went through the production seam deliberately, saying so.
                continued = [
                    record
                    for record in caplog.records
                    if "turn.checkpoint_continue" in str(record.msg)
                ]
                assert continued, "the takeover did not go through the checkpoint-continue branch"
            finally:
                runner.release.set()
                worker_b.stop()
                task_b.cancel()
                await asyncio.gather(task_b, return_exceptions=True)
                await _drop_checkpoint_thread(run_id)

    run_async(scenario())


async def _checkpoint_rows(thread_id: str) -> int:
    """How many LangGraph checkpoint rows exist for this thread (0 when the saver table is absent).

    Read straight off ``checkpoints`` rather than through a saver: the point is that the state is
    durable in the platform database, visible to any process, not merely reachable from the object
    that wrote it.
    """
    async with transaction() as conn:
        present = (
            await conn.execute(text("SELECT to_regclass('public.checkpoints')"))
        ).scalar_one()
        if present is None:
            return 0
        return int(
            (
                await conn.execute(
                    text("SELECT count(*) FROM checkpoints WHERE thread_id = :t"),
                    {"t": thread_id},
                )
            ).scalar_one()
        )


async def _drop_checkpoint_thread(thread_id: str) -> None:
    """The saver's tables sit outside Alembic and outside the rollback — clean up by hand."""
    async with transaction() as conn:
        for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            present = (
                await conn.execute(text(f"SELECT to_regclass('public.{table}')"))
            ).scalar_one()
            if present is not None:
                await conn.execute(
                    text(f"DELETE FROM {table} WHERE thread_id = :t"), {"t": thread_id}
                )


def test_two_workspaces_drain_concurrently_without_blocking_each_other() -> None:
    from lumen_api.fleet_handler import DesignTurnHost, build_design_job_handler

    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                workspace_a = await _seed_workspace(conn, "conc_a")
                workspace_b = await _seed_workspace(conn, "conc_b")
            run_a, _ = await _offer_turn(workspace_a, "poster for tenant A")
            run_b, _ = await _offer_turn(workspace_b, "poster for tenant B")

            # Each turn parks until BOTH have been claimed. If the two drains were serialized the
            # first turn could never be released and this test would time out — which is exactly
            # the property being asserted, rather than a timing coincidence.
            both_started = threading.Event()
            started = threading.Semaphore(0)

            def runner(payload: Any, root: Any) -> dict[str, Any]:
                started.release()
                assert both_started.wait(timeout=20)
                return {"schema_version": 1, "status": "proposed", "summary": payload.prompt}

            handler = build_design_job_handler(
                host_provider=lambda: DesignTurnHost(agent_turn_runner=runner),
                checkpointer_factory=None,
            )
            workers = [_build_worker(handler, f"worker-conc-{index}") for index in range(2)]
            tasks = [asyncio.create_task(worker.run()) for worker in workers]
            try:

                async def both_claimed() -> bool | None:
                    return True if started._value >= 2 else None  # noqa: SLF001 - test probe

                await _await_condition(both_claimed, label="both turns claimed concurrently")
                both_started.set()

                async def both_done() -> bool | None:
                    first = await _read_run(workspace_a, run_a)
                    second = await _read_run(workspace_b, run_b)
                    return (
                        True
                        if first["status"] == "succeeded" and second["status"] == "succeeded"
                        else None
                    )

                await _await_condition(both_done, label="both turns complete")

                first = await _read_run(workspace_a, run_a)
                second = await _read_run(workspace_b, run_b)
                assert first["result"]["summary"] == "poster for tenant A"
                assert second["result"]["summary"] == "poster for tenant B"
                assert first["leased_by"] != second["leased_by"]
            finally:
                for worker in workers:
                    worker.stop()
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    run_async(scenario())


# --- the session probe (2026-09-18) -------------------------------------------------------------
#
# What the handler asks the saver before handing the turn to an executor: "has this thread run
# before?" The answer decides whether the turn re-sends the delegation brief and the leg history
# or leaves them to the state the thread already holds. No database — the contract is entirely
# about what the probe does with the three answers a saver can give.


def test_the_session_probe_reads_the_threads_state_through_the_saver() -> None:
    from lumen_api.fleet_handler import _thread_has_state

    asked: list[dict[str, Any]] = []

    class _Saver:
        def __init__(self, tuple_: Any) -> None:
            self._tuple = tuple_

        def get_tuple(self, config: dict[str, Any]) -> Any:
            asked.append(config)
            return self._tuple

    assert _thread_has_state(_Saver(object()), "dsess_abc") is True
    assert _thread_has_state(_Saver(None), "dsess_abc") is False
    assert asked == [{"configurable": {"thread_id": "dsess_abc"}}] * 2


def test_a_saver_that_cannot_answer_never_fails_the_turn() -> None:
    """A probe is a convenience; a turn is paid work. An unreadable thread reads as FRESH, which
    costs one re-sent brief and never a lost one."""
    from lumen_api.fleet_handler import _thread_has_state

    class _Broken:
        def get_tuple(self, config: dict[str, Any]) -> Any:
            raise RuntimeError("the saver is down")

    assert _thread_has_state(_Broken(), "dsess_abc") is False
    # No checkpointer at all (the CLI / fixture composition) is the same answer.
    assert _thread_has_state(None, "dsess_abc") is False
