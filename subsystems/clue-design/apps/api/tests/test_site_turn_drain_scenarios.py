"""Graceful drain on deploy for queued site turns (site-turn durability, Task 4), design side.

A worker being shut down (SIGTERM) stops taking tasks and lets its running site turn finish. A turn
still running when the worker's drain bound passes stops at its next step boundary: its working copy
and checkpoint are saved, the task goes back to the queue, and the run is NOT failed. The next worker
continues the turn from the copy and asks the model for nothing the first attempt finished.

Everything here is the shipped object: the fleet's ``LeasedWorkWorker`` with its real Postgres work
leases, the production design job handler (``build_design_job_handler``, the Postgres checkpointer),
the real executor, harness, tools, validator and save. Only two things stand in: the chat model (the
Lane B seam, see ``test_site_lane_b_scenarios``) and the fleet QUEUE, a one-task list, so no worker
here can claim another suite's task from the shared table. SIGTERM is ``worker.stop()``, which is
exactly what the process's signal handler calls (``clue_fleet.runner``).
"""

# The Lane B fixtures are imported by name; pytest injects them into the tests' parameters.
# ruff: noqa: F811

from __future__ import annotations

import asyncio
import threading
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from clue_db import db_lifespan
from clue_fleet import DbWorkLeaseStore, FleetTaskKind, FleetTaskStatus, LeasedWorkWorker, WorkTaskRow
from test_site_lane_b_scenarios import (  # noqa: F401 - fixtures are used by name
    CTA_A,
    PROOF_A,
    REQUEST_1,
    Garner,
    ModelSeam,
    _agent_root,
    another_disk,
    call,
    checkpoint_rows,
    client,
    edit_heading_call,
    envelope_for,
    fresh_site_run,
    garner,
    model,
    open_run,
    proof_edit,
    run_columns,
    session_folder,
    tool_results_in,
    turn_host,
    with_heading,
)


class OneTaskQueue:
    """The fleet queue holding just this test's task (``WorkQueue``'s shape, in memory)."""

    def __init__(self, task: WorkTaskRow) -> None:
        self.rows = deque([task])
        self.finished: list[tuple[Any, FleetTaskStatus, dict]] = []
        self.requeued: list[Any] = []
        self.claims = 0

    async def claim_next(self, *, kind, worker_id, **_: Any):
        self.claims += 1
        if kind is not FleetTaskKind.DESIGN_JOB or not self.rows:
            return None
        row = self.rows.popleft()
        return row.model_copy(update={"status": FleetTaskStatus.CLAIMED, "claimed_by": worker_id,
                                      "claimed_at": datetime.now(UTC), "attempts": row.attempts + 1})

    async def finish(self, *, task_id, worker_id, status, result_ref=None) -> bool:
        self.finished.append((task_id, status, dict(result_ref or {})))
        return True

    async def requeue(self, *, task_id, worker_id, delay=None, uncount_attempt=False) -> bool:
        self.requeued.append(task_id)
        return True

    async def touch(self, *, task_id, worker_id) -> bool:
        return True


def design_task(envelope: Any) -> WorkTaskRow:
    now = datetime.now(UTC)
    return WorkTaskRow(
        task_id=uuid4(), kind=FleetTaskKind.DESIGN_JOB, work_id=envelope.work_id, dedup_key=str(envelope.work_id),
        priority=0, status=FleetTaskStatus.QUEUED, attempts=0, payload=envelope.model_dump(mode="json"),
        result_ref={}, claimed_by=None, claimed_at=None, available_at=now, enqueued_at=now, enqueue_seq=1,
        updated_at=now,
    )


def design_worker(app: Any, queue: OneTaskQueue, worker_id: str, *, drain_bound: timedelta) -> tuple[LeasedWorkWorker, Any]:
    """A design worker as ``fleet_main`` composes it, over this test's one-task queue."""
    from lumen_api.fleet_handler import build_design_job_handler

    handler = build_design_job_handler(host_provider=lambda: turn_host(app), named_trace=False)
    worker = LeasedWorkWorker(handlers=(handler,), queue=queue, leases=DbWorkLeaseStore(), worker_id=worker_id,
                              poll_interval=0.01, drain_bound=drain_bound)
    return worker, handler


class Sigterm:
    """Sends the worker its SIGTERM (``worker.stop()``) from inside the turn's thread."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.worker: LeasedWorkWorker | None = None

    def __call__(self) -> None:
        assert self.loop is not None and self.worker is not None
        self.loop.call_soon_threadsafe(self.worker.stop)

    async def run(self, worker: LeasedWorkWorker) -> None:
        self.loop, self.worker = asyncio.get_running_loop(), worker
        async with db_lifespan():
            await worker.run()


def drain_once(worker: LeasedWorkWorker) -> bool:
    async def once() -> bool:
        async with db_lifespan():
            return await worker.drain_once()

    return asyncio.run(asyncio.wait_for(once(), timeout=300))


def latest_checkpoint_id(run_id: str) -> str:
    from lumen_api.fleet_handler import postgres_design_checkpointer

    with postgres_design_checkpointer(run_id) as saver:
        return saver.get_tuple({"configurable": {"thread_id": run_id}}).config["configurable"]["checkpoint_id"]


def test_k_a_sigterm_during_a_queued_site_turn_lets_it_finish_and_save(
        client: TestClient, model: ModelSeam, garner: Garner, _agent_root: Path) -> None:
    store, document_id, born, envelope = fresh_site_run(garner)
    queue = OneTaskQueue(design_task(envelope))
    worker, _handler = design_worker(client.app, queue, "worker-k-a", drain_bound=timedelta(minutes=10))
    sigterm = Sigterm()
    # SIGTERM arrives after the edit landed, while the agent writes its answer.
    model.next(*proof_edit(born, PROOF_A, 1), hooks={1: sigterm})

    asyncio.run(asyncio.wait_for(sigterm.run(worker), timeout=300))

    assert worker.stopping
    ((_, status, result),) = queue.finished
    assert status is FleetTaskStatus.DONE and result["outcome"] == "succeeded", result
    assert queue.requeued == [] and queue.claims == 1
    stored = store.require_document(document_id)
    assert stored["current_version"] == 1 and stored["scene"] == with_heading(born, "/", "proof", PROOF_A)
    assert store.require_run(envelope.run_id)["status"] == "succeeded"


def test_k_b_a_turn_still_running_at_the_bound_stops_at_a_step_and_the_next_worker_finishes_it(
        client: TestClient, model: ModelSeam, garner: Garner, _agent_root: Path) -> None:
    store, document_id, born, envelope = fresh_site_run(garner)
    task = design_task(envelope)
    queue_a = OneTaskQueue(task)
    worker_a, handler_a = design_worker(client.app, queue_a, "worker-k-b-a", drain_bound=timedelta(seconds=0.2))
    asked = threading.Event()
    real_request_drain = handler_a.request_drain

    def request_drain(reason: str) -> None:
        real_request_drain(reason)
        asked.set()

    def the_bound_passes() -> None:
        assert asked.wait(30), "the worker never asked the turn to drain"

    handler_a.request_drain = request_drain
    sigterm = Sigterm()
    a = model.next(
        AIMessage(content="", tool_calls=[edit_heading_call(born, "/", "proof", PROOF_A, 1)]),
        # The bound passes while this answer is produced: the answer stands, its edit waits.
        AIMessage(content="", tool_calls=[edit_heading_call(born, "/analysis", "cta", CTA_A, 2)]),
        AIMessage(content="never reached"),
        hooks={0: sigterm, 1: the_bound_passes},
    )

    asyncio.run(asyncio.wait_for(sigterm.run(worker_a), timeout=300))

    # A stopped at the step boundary after its second answer: handed back, not failed, nothing saved.
    assert asked.is_set() and len(a.seen) == 2
    assert queue_a.finished == [] and queue_a.requeued == [task.task_id]
    columns = run_columns(envelope.run_id)
    assert columns["status"] == "running" and columns["leased_by"] == "worker-k-b-a", columns
    generation_a = columns["lease_generation"]
    assert store.require_run(envelope.run_id)["result"] is None
    assert store.require_document(document_id)["current_version"] == 0
    copy = store.get_site_turn_workspace(envelope.run_id)
    assert copy["checkpoint_id"] == latest_checkpoint_id(envelope.run_id)
    assert PROOF_A in copy["files"]["page.json"] and CTA_A not in copy["files"]["pages/analysis.json"]
    # A drained attempt writes no history: the request belongs to the attempt that finishes it.
    history = session_folder(_agent_root, store.workspace_id, document_id) / "workspace" / "history.md"
    assert not history.exists() or REQUEST_1 not in history.read_text()

    # The next worker, on another disk, takes the requeued task and continues from A's step.
    another_disk(_agent_root, store, document_id)
    queue_b = OneTaskQueue(task)
    worker_b, _ = design_worker(client.app, queue_b, "worker-k-b-b", drain_bound=timedelta(minutes=10))
    b = model.next(AIMessage(content="", tool_calls=[call("validate_page", {}, 13)]),
                   AIMessage(content="Both headings are updated."))
    assert drain_once(worker_b)

    # B was never asked for A's answers: its first call already holds both edits' results.
    assert len(b.seen) == 2 and {"call_1", "call_2"} <= tool_results_in(b.seen[0])
    assert b.text_of("call_13") == "VALID."
    ((_, status, result),) = queue_b.finished
    assert status is FleetTaskStatus.DONE and result["outcome"] == "succeeded", result
    both = with_heading(with_heading(born, "/", "proof", PROOF_A), "/analysis", "cta", CTA_A)
    stored = store.require_document(document_id)
    assert stored["current_version"] == 1 and stored["scene"] == both
    finished = run_columns(envelope.run_id)
    assert finished["status"] == "succeeded" and finished["lease_generation"] > generation_a
    assert store.get_site_turn_workspace(envelope.run_id) is None and checkpoint_rows(envelope.run_id) == 0


def test_k_c_a_drained_attempt_writes_no_history_and_never_moves_the_session_copy(
        client: TestClient, model: ModelSeam, garner: Garner, _agent_root: Path) -> None:
    """A drained attempt still holds its run, so the session-memory fence would let it through: it
    must stop before any history entry, snapshot or session save. A first request gives the site its
    history and session copy (version 1); a second request is drained mid-turn and leaves both
    exactly as they were, and its attempt folder is gone."""
    store, document_id, born, first = fresh_site_run(garner)
    queue = OneTaskQueue(design_task(first))
    worker, _ = design_worker(client.app, queue, "worker-k-c-1", drain_bound=timedelta(minutes=10))
    model.next(*proof_edit(born, PROOF_A, 1))
    assert drain_once(worker)
    assert queue.finished[0][2]["outcome"] == "succeeded"
    folder = session_folder(_agent_root, store.workspace_id, document_id)
    history_before = (folder / "workspace" / "history.md").read_text()
    session_before = store.get_site_session(document_id)
    assert session_before is not None and int(session_before["version"]) == 1

    second = envelope_for(document_id, store.workspace_id, "Now warm up the closing call to action.")
    open_run(store, second, claim=False)
    queue_2 = OneTaskQueue(design_task(second))
    worker_2, handler_2 = design_worker(client.app, queue_2, "worker-k-c-2", drain_bound=timedelta(seconds=0.2))
    sigterm = Sigterm()
    asked = threading.Event()
    real_request_drain = handler_2.request_drain

    def request_drain(reason: str) -> None:
        real_request_drain(reason)
        asked.set()

    def the_bound_passes() -> None:
        assert asked.wait(30), "the worker never asked the turn to drain"

    handler_2.request_drain = request_drain
    current = with_heading(born, "/", "proof", PROOF_A)
    model.next(
        AIMessage(content="", tool_calls=[edit_heading_call(current, "/analysis", "cta", CTA_A, 1)]),
        AIMessage(content="", tool_calls=[call("validate_page", {}, 2)]),
        AIMessage(content="never reached"),
        hooks={0: sigterm, 1: the_bound_passes},
    )
    asyncio.run(asyncio.wait_for(sigterm.run(worker_2), timeout=300))

    assert queue_2.finished == [] and len(queue_2.requeued) == 1
    assert run_columns(second.run_id)["status"] == "running"
    assert (folder / "workspace" / "history.md").read_text() == history_before
    session_after = store.get_site_session(document_id)
    assert session_after["version"] == session_before["version"]
    assert session_after["manifest_sha256"] == session_before["manifest_sha256"]
    assert not any(path.name.startswith(second.run_id) for path in (folder / "attempts").glob("*"))
    assert store.require_document(document_id)["current_version"] == 1
